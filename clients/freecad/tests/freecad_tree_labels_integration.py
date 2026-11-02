"""Isolated HTTP/CAD regression for labels in upload, revision and retrieval.

Start freecad_phase4_smoke.py --serve CASE_DIR, then invoke run(App, Gui, CASE_DIR)
through MCP. Restores the existing user session and documents afterward.
"""


def run(App, Gui, case_directory):
    from concurrent.futures import ThreadPoolExecutor
    import hashlib
    import json
    from pathlib import Path
    import sys

    import freecad.forgepdm as package
    from freecad.forgepdm import api, cad, commands, session, tree_observer, ui, workspace

    case = Path(case_directory)
    config = json.loads((case / "connection.json").read_text())
    original_client, original_user = session.Session.client, session.Session.user
    original_names = set(App.listDocuments())
    active = App.ActiveDocument.Name if App.ActiveDocument else None
    originals = {
        name: getattr(commands, name)
        for name in (
            "ask_choice",
            "ask_text",
            "_choose_workspace",
            "information",
            "warning",
            "select_replacement_occurrences",
            "review_component_replacement",
        )
    }
    executor = ThreadPoolExecutor(max_workers=1)
    report = {
        "freecad": App.Version(),
        "python": sys.version,
        "qt": ui.QtCore.qVersion(),
        "addon_version": package.__version__,
        "checks": [],
        "scope": "Actual command workflows, isolated disposable HTTP database/blobs/workspace; user session and documents restored",
    }
    selected = {"kind": "part"}

    def check(label, value):
        assert value, label
        report["checks"].append(label)

    def worker(function, *args, **kwargs):
        future = executor.submit(function, *args, **kwargs)
        loop = ui.QtCore.QEventLoop()
        timer = ui.QtCore.QTimer()
        timer.timeout.connect(lambda: loop.quit() if future.done() else None)
        timer.start(5)
        if not future.done():
            loop.exec()
        timer.stop()
        return future.result(timeout=1)

    def drive(workflow):
        value = None
        while True:
            try:
                request = workflow.send(value)
            except StopIteration:
                return
            value = worker(request.function, *request.args, **request.kwargs)

    def source(name):
        document = App.newDocument(name)
        path = case / (name + ".FCStd")
        document.saveAs(str(path))
        return document

    def upload(document, kind):
        selected["kind"] = kind
        App.setActiveDocument(document.Name)
        drive(commands.UploadCommand().action())
        return dict(workspace.binding(document.FileName, client.base_url)["entry"])

    def retrieve(entry):
        configuration = worker(
            client.retrieve_configuration,
            str(case / "retrievals"),
            entry["revision_id"],
            entry["dataset_id"],
            entry["file_id"],
        )
        result = cad.open_configuration(configuration, commands._set_metadata)
        worker(client.finish_configuration, configuration)
        return result

    client = api.ForgePDMClient(config["base_url"])
    try:
        user = worker(client.login, config["username"], config["password"])
        session.Session.set_client(client, user)
        commands.ask_choice = lambda title, prompt, choices, *args: (
            selected["kind"]
            if title == "New ForgePDM Item"
            else (choices[-1] if title == "CAD Snapshots" else choices[0])
        )
        commands.ask_text = lambda *args, **kwargs: "Tree labels integration revision"
        commands._choose_workspace = lambda *args: str(case / "working")
        commands.information = commands.warning = lambda *args: None

        child = source("LabelsIntegrationPart")
        box = child.addObject("Part::Box", "Box")
        box.Length, box.Width, box.Height = 10, 2, 3
        child.recompute()
        upload(child, "part")
        part_number = child.getObject("ForgePDM_Metadata").ItemNumber
        check(
            "new part upload derives its item/revision heading", child.Label == part_number + "-A"
        )
        child_a_path = Path(child.FileName)
        child_a_hash = hashlib.sha256(child_a_path.read_bytes()).hexdigest()

        root = source("LabelsIntegrationAssembly")
        group = root.addObject("Assembly::AssemblyObject", "Assembly")
        first = root.addObject("App::Link", "First")
        first.setLink(box)
        group.addObject(first)
        repeat = root.addObject("App::Link", "Repeat")
        repeat.setLink(box)
        group.addObject(repeat)
        repeat.Placement.Base = App.Vector(25, 0, 0)
        import JointObject

        joints = root.addObject("Assembly::JointGroup", "Joints")
        grounded = root.addObject("App::FeaturePython", "Grounded")
        JointObject.GroundedJoint(grounded, first)
        group.addObject(joints)
        group.addObject(grounded)
        joints.addObject(grounded)
        root.recompute()
        root_entry = upload(root, "assembly")
        ids = (first.ForgePDMOccurrenceId, repeat.ForgePDMOccurrenceId)
        check(
            "assembly upload persists distinct repeated occurrence labels",
            (first.Label, repeat.Label) == (part_number + "-A|1", part_number + "-A|2"),
        )
        manifest = worker(client.get_manifest, root_entry["dataset_id"])
        check(
            "labels preserve manifest internal object identities",
            {ref["object_name"] for ref in manifest["references"]} == {"First", "Repeat"},
        )
        opened = retrieve(root_entry)
        retrieved = opened["root"]
        check(
            "owned retrieval preserves occurrence IDs and indices",
            (retrieved.First.ForgePDMOccurrenceId, retrieved.Repeat.ForgePDMOccurrenceId) == ids
            and (retrieved.First.Label, retrieved.Repeat.Label)
            == (part_number + "-A|1", part_number + "-A|2"),
        )
        check(
            "retrieved labels leave every document saved cleanly",
            all(not cad.document_modified(doc) for doc in opened["owned"]),
        )
        check("retrieved placement remains unchanged", retrieved.Repeat.Placement.Base.x == 25)
        cad.close_owned(opened["owned"])

        App.setActiveDocument(child.Name)
        drive(commands.CheckInCommand().action())
        drive(commands.ReleaseCommand().action())
        child_a_hash = hashlib.sha256(child_a_path.read_bytes()).hexdigest()
        source_child, source_box = child, box
        drive(commands.NewRevisionCommand().action())
        child = App.ActiveDocument
        box = child.getObject(source_box.Name)
        check("new revision is a distinct live document", child is not source_child)
        check(
            "open parent still targets original document",
            root.First.LinkedObject.Document is source_child,
        )
        check(
            "original live revision identity remains A",
            source_child.getObject("ForgePDM_Metadata").RevisionLabel == "A",
        )
        box.Length = 15
        child.recompute()
        upload(child, "part")
        check(
            "next revision changes the managed document heading", child.Label == part_number + "-B"
        )
        check(
            "next revision preserves prior native file bytes",
            hashlib.sha256(child_a_path.read_bytes()).hexdigest() == child_a_hash,
        )
        check(
            "live parent keeps original revision and geometry after editing B",
            root.First.Label == part_number + "-A|1" and root.First.LinkedObject.Length.Value == 10,
        )
        check("original live document stays clean", not cad.document_modified(source_child))
        historical = retrieve(root_entry)
        old_root = historical["root"]
        check(
            "historical assembly keeps revision A labels after part B exists",
            (old_root.First.Label, old_root.Repeat.Label)
            == (part_number + "-A|1", part_number + "-A|2"),
        )
        check(
            "historical occurrence UUIDs remain pinned",
            (old_root.First.ForgePDMOccurrenceId, old_root.Repeat.ForgePDMOccurrenceId) == ids,
        )
        check(
            "historical geometry stays on exact part A",
            old_root.First.LinkedObject.Length.Value == 10 and box.Length.Value == 15,
        )
        check(
            "tree labeling does not create engineering BOM lines",
            worker(client.get_bom, root_entry["revision_id"]) == [],
        )
        cad.close_owned(historical["owned"])

        # Grounded native assemblies can become Touched after loading dependencies.
        # Explicitly save/upload before entering the clean-parent replacement flow.
        upload(root, "assembly")
        # Exercise explicit replacement independently of creating the revision.
        App.setActiveDocument(root.Name)
        commands.select_replacement_occurrences = lambda rows, selected: ["First"]
        commands.review_component_replacement = lambda *args: False
        names_before = set(App.listDocuments())
        drive(commands.ReplaceRevisionCommand().action())
        check(
            "cancel replacement preserves all open documents",
            set(App.listDocuments()) == names_before,
        )
        check(
            "cancel replacement keeps original target and clean assembly",
            first.LinkedObject is source_box and not cad.document_modified(root),
        )
        commands.review_component_replacement = lambda *args: True
        saved_root_hash = workspace.digest(root.FileName)
        before_names = [obj.Name for obj in group.Group]
        drive(commands.ReplaceRevisionCommand().action())
        replacement_target = first.LinkedObject
        check(
            "selected occurrence uses exact chosen B geometry",
            replacement_target.Length.Value == 15
            and replacement_target.Document.getObject("ForgePDM_Metadata").RevisionLabel == "B",
        )
        check(
            "unselected repeated occurrence stays on A",
            repeat.LinkedObject is source_box and repeat.LinkedObject.Length.Value == 10,
        )
        check(
            "replacement retains placement and occurrence UUIDs",
            repeat.Placement.Base.x == 25
            and (first.ForgePDMOccurrenceId, repeat.ForgePDMOccurrenceId) == ids,
        )
        check(
            "grounded joint and assembly members are preserved",
            grounded.ObjectToGround is first and [obj.Name for obj in group.Group] == before_names,
        )
        check(
            "replacement leaves unsaved local changes without writing BOM or file",
            cad.document_modified(root)
            and workspace.digest(root.FileName) == saved_root_hash
            and worker(client.get_bom, root_entry["revision_id"]) == [],
        )
        upload(root, "assembly")
        refs = cad.capture_bom(root)
        prepared = worker(client.prepare_cad_bom, root.FileName, root_entry["revision_id"], refs)
        check(
            "explicit later upload pins both chosen B and retained A",
            {ref["target_revision_id"] for ref in prepared["references"]}
            == {
                source_child.getObject("ForgePDM_Metadata").RevisionId,
                child.getObject("ForgePDM_Metadata").RevisionId,
            },
        )
        from freecad.forgepdm import replacement

        original_refresh = replacement.tree_labels.refresh
        try:

            def fail_refresh(*args, **kwargs):
                raise RuntimeError("Injected label failure to verify real transaction rollback")

            replacement.tree_labels.refresh = fail_refresh
            try:
                replacement.apply(
                    root,
                    refs,
                    ["Repeat"],
                    replacement_target.Document,
                    worker(client.get_revision, child.getObject("ForgePDM_Metadata").RevisionId),
                )
            except RuntimeError:
                check(
                    "real replacement transaction rolls back targets on failure",
                    repeat.LinkedObject is source_box and grounded.ObjectToGround is first,
                )
            else:
                raise AssertionError("Injected replacement failure was accepted")
        finally:
            replacement.tree_labels.refresh = original_refresh
        report["status"] = "passed"
    except BaseException as error:
        report.update({"status": "failed", "error": str(error)})
        raise
    finally:
        for name, function in originals.items():
            setattr(commands, name, function)
        for name in list(App.listDocuments()):
            if name not in original_names:
                document = App.getDocument(name)
                metadata = document.getObject("ForgePDM_Metadata")
                if metadata:
                    tree_observer.revoke_revision(metadata.RevisionId)
                App.closeDocument(name)
        session.Session.set_client(original_client, original_user)
        if active:
            App.setActiveDocument(active)
        executor.shutdown(wait=True)
        (case / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
