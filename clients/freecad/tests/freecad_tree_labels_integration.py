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
        for name in ("ask_choice", "ask_text", "_choose_workspace", "information", "warning")
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
            selected["kind"] if title == "New ForgePDM Item" else choices[0]
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
        drive(commands.NewRevisionCommand().action())
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
