"""Real FreeCAD/HTTP multi-user refresh harness; invoke run(App, Gui, case)."""


def run(App, Gui, directory, component_updates=False, tree_status_checks=False):
    import importlib
    import json
    import secrets
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path
    from threading import get_ident

    import freecad.forgepdm as package

    source = Path(__file__).resolve().parents[1] / "freecad/forgepdm"
    previous_package_path = list(package.__path__)
    if str(source) not in package.__path__:
        package.__path__.insert(0, str(source))
    from freecad.forgepdm import (
        api,
        cad,
        commands,
        replacement,
        server_updates,
        session,
        tree_observer,
        ui,
        workspace,
    )

    importlib.reload(api)
    importlib.reload(replacement)
    importlib.reload(server_updates)
    importlib.reload(commands)
    case = Path(directory)
    config = json.loads((case / "connection.json").read_text())
    previous_session = session.Session.client, session.Session.user
    original_names = set(App.listDocuments())
    original_active = App.ActiveDocument.Name if App.ActiveDocument else None
    original_files = {
        d.FileName: workspace.digest(d.FileName)[0]
        for d in App.listDocuments().values()
        if d.FileName
    }
    originals = {
        name: getattr(commands, name)
        for name in (
            "ask_choice",
            "_choose_workspace",
            "information",
            "warning",
            "select_replacement_occurrences",
            "review_component_replacement",
        )
    }
    executor = ThreadPoolExecutor(max_workers=1)
    main_thread, worker_threads = get_ident(), []
    report = {
        "freecad": App.Version(),
        "checks": [],
        "scope": "Real FreeCAD geometry, disposable HTTP DB/storage, two users and workspaces; automated review choices",
    }
    messages = []
    selected = {"workspace": "alice", "approve": True, "kind": "part"}

    def check(label, condition):
        assert condition, label
        report["checks"].append(label)

    def worker(function, *args, **kwargs):
        def execute():
            worker_threads.append(get_ident())
            return function(*args, **kwargs)

        future = executor.submit(execute)
        loop, timer = ui.QtCore.QEventLoop(), ui.QtCore.QTimer()
        timer.timeout.connect(lambda: loop.quit() if future.done() else None)
        timer.start(5)
        if not future.done():
            loop.exec()
        timer.stop()
        return future.result()

    def drive(command):
        workflow, value = command.action(), None
        while True:
            try:
                request = workflow.send(value)
            except StopIteration:
                return
            try:
                value = worker(request.function, *request.args, **request.kwargs)
            except BaseException as error:
                workflow.throw(error)
                raise

    def choose(title, prompt, options, *args):
        if title == "New ForgePDM Item":
            return selected["kind"]
        if title == "Update from Server":
            return "Open updated copy" if selected["approve"] else "Cancel"
        return options[0]

    alice = api.ForgePDMClient(config["base_url"])
    bob = api.ForgePDMClient(config["base_url"])
    try:
        alice_user = worker(alice.login, config["username"], config["password"])
        temporary, password = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
        bob_username = "refresh-bob-" + secrets.token_hex(4)
        worker(
            alice._json_request,
            "POST",
            "/api/v1/admin/users",
            dict(
                username=bob_username, display_name="Refresh Bob", password=temporary, role="admin"
            ),
        )
        worker(bob.login, bob_username, temporary)
        worker(
            bob._json_request,
            "POST",
            "/api/v1/auth/password",
            dict(current_password=temporary, new_password=password),
        )
        bob_user = worker(bob.login, bob_username, password)
        commands.ask_choice = choose
        commands._choose_workspace = lambda *a: str(case / selected["workspace"])
        commands.information = commands.warning = lambda title, text: messages.append(text)
        session.Session.set_client(alice, alice_user)
        document = App.newDocument("ServerUpdateFixture")
        box = document.addObject("Part::Box", "Box")
        box.Length = 10
        document.recompute()
        document.saveAs(str(case / "source.FCStd"))
        drive(commands.UploadCommand())
        drive(commands.CheckInCommand())
        metadata = document.getObject("ForgePDM_Metadata")
        item_id, revision_id = metadata.ItemId, metadata.RevisionId
        baseline = worker(alice.inspect_server_update, document.FileName, item_id, revision_id)
        check("initial upload is current", not baseline["changed"])
        dataset, record = baseline["dataset"], baseline["file"]
        if component_updates:
            import JointObject

            parent = App.newDocument("ComponentSnapshotUpdateFixture")
            parent.saveAs(str(case / "parent.FCStd"))
            assembly = parent.addObject("Assembly::AssemblyObject", "Assembly")
            for name, x in (("First", 0), ("Second", 50)):
                link = parent.addObject("App::Link", name)
                link.setLink(box)
                link.Placement.Base.x = x
                assembly.addObject(link)
            joint = parent.addObject("App::FeaturePython", "Grounded")
            JointObject.GroundedJoint(joint, parent.getObject("First"))
            joints = parent.addObject("Assembly::JointGroup", "Joints")
            assembly.addObject(joints)
            joints.addObject(joint)
            parent.recompute()
            parent.saveAs(str(case / "parent.FCStd"))
            selected["kind"] = "assembly"
            drive(commands.UploadCommand())
            drive(commands.CheckInCommand())
            selected["kind"] = "part"
        configuration = worker(
            bob.retrieve_configuration, str(case / "bob"), revision_id, dataset["id"], record["id"]
        )
        opened = cad.open_configuration(configuration, commands._set_metadata)
        worker(bob.finish_configuration, configuration)
        bob_document = opened["root"]
        session.Session.set_client(bob, bob_user)
        selected["workspace"] = "bob"
        drive(commands.CheckoutCommand())
        bob_document.getObject("Box").Length = 25
        bob_document.recompute()
        drive(commands.CheckInCommand())
        check(
            "second user checked in changed geometry", worker(bob.get_checkout, revision_id) is None
        )
        session.Session.set_client(alice, alice_user)
        if component_updates:
            App.setActiveDocument(parent.Name)
            selected["workspace"] = "alice"
            commands.select_replacement_occurrences = lambda *a: ["First"]
            commands.review_component_replacement = lambda *a: selected["approve"]
            try:
                drive(commands.UpdateSelectedComponentsCommand())
            except workspace.WorkspaceError:
                check(
                    "component update requires owned parent checkout",
                    parent.getObject("First").LinkedObject is box,
                )
            else:
                raise AssertionError("Update without parent checkout allowed")
            drive(commands.CheckoutCommand())
            drive(commands.UploadCommand())
            parent_revision = parent.getObject("ForgePDM_Metadata").RevisionId
            parent_path = parent.FileName
            parent_hash = workspace.digest(parent_path)[0]
            original_pins = worker(alice.validate_references, cad.capture_bom(parent))
            identities = {n: parent.getObject(n).ForgePDMOccurrenceId for n in ("First", "Second")}
            placements = {n: parent.getObject(n).Placement for n in ("First", "Second")}
            labels = {n: parent.getObject(n).Label for n in ("First", "Second")}
            sources_hash = workspace.digest(document.FileName)[0]
            count = len(worker(alice.list_datasets, parent_revision))
            bom_before = worker(alice.get_bom, parent_revision)
            selected["approve"] = False
            docs_before = set(App.listDocuments())
            drive(commands.UpdateSelectedComponentsCommand())
            check(
                "component review cancellation preserves targets",
                parent.getObject("First").LinkedObject is box,
            )
            check(
                "component cancellation cleans retrieved documents",
                set(App.listDocuments()) == docs_before,
            )
            selected["approve"] = True
            drive(commands.UpdateSelectedComponentsCommand())
            first, second = parent.getObject("First"), parent.getObject("Second")
            check(
                "selected component adopts other user's same-revision geometry",
                first.LinkedObject.Length.Value == 25,
            )
            check(
                "unselected component keeps original geometry and target",
                second.LinkedObject is box and box.Length.Value == 10,
            )
            check(
                "component revision remains unchanged",
                first.LinkedObject.Document.getObject("ForgePDM_Metadata").RevisionId
                == revision_id,
            )
            check(
                "occurrence UUIDs preserved",
                all(parent.getObject(n).ForgePDMOccurrenceId == identities[n] for n in identities),
            )
            check(
                "component placements preserved",
                all(parent.getObject(n).Placement == placements[n] for n in placements),
            )
            check(
                "same-revision occurrence labels preserved",
                all(parent.getObject(n).Label == labels[n] for n in labels),
            )
            check("grounded joint preserved", parent.getObject("Grounded").ObjectToGround is first)
            check("parent stays modified for inspection", cad.document_modified(parent))
            check(
                "parent file and source file bytes untouched",
                workspace.digest(parent_path)[0] == parent_hash
                and workspace.digest(document.FileName)[0] == sources_hash,
            )
            check(
                "component update does not publish parent or BOM",
                len(worker(alice.list_datasets, parent_revision)) == count
                and worker(alice.get_bom, parent_revision) == bom_before,
            )
            check(
                "component update preserves parent checkout",
                worker(alice.get_checkout, parent_revision)["user_id"] == alice_user["id"],
            )
            drive(commands.CheckInCommand())
            new_pins = worker(alice.validate_references, cad.capture_bom(parent))
            check(
                "explicit check-in persists mixed exact snapshot pins",
                new_pins[0]["target_file_id"] != original_pins[0]["target_file_id"]
                and new_pins[1]["target_file_id"] == original_pins[1]["target_file_id"],
            )
            uploaded = workspace.binding(parent.FileName, alice.base_url)["entry"]
            manifest = worker(alice.get_manifest, uploaded["dataset_id"])
            manifest_pins = {
                ref["object_name"]: ref["target_file_id"] for ref in manifest["references"]
            }
            check(
                "server manifest matches reviewed occurrence pins",
                all(manifest_pins[ref["object_name"]] == ref["target_file_id"] for ref in new_pins),
            )
            drive(commands.CheckoutCommand())
            drive(commands.UploadCommand())
            drive(commands.UpdateSelectedComponentsCommand())
            check(
                "current selected occurrence reports no update",
                "already use the latest" in messages[-1],
            )
            check("component HTTP work stays off GUI thread", main_thread not in worker_threads)
            if tree_status_checks:
                from importlib.util import spec_from_file_location, module_from_spec

                spec = spec_from_file_location(
                    "tree_status_acceptance",
                    source.parents[1] / "tests/freecad_tree_status_integration.py",
                )
                status_harness = module_from_spec(spec)
                spec.loader.exec_module(status_harness)
                status_harness.run(
                    App,
                    Gui,
                    case,
                    worker,
                    check,
                    alice,
                    bob,
                    alice_user,
                    bob_user,
                    parent,
                    item_id,
                    revision_id,
                )
            report["status"] = "passed"
            return report
        App.setActiveDocument(document.Name)
        old_path = document.FileName
        old_hash = workspace.digest(old_path)[0]
        original_count = len(App.listDocuments())
        selected["approve"] = False
        drive(commands.UpdateFromServerCommand())
        check(
            "cancel preserves original document count", len(App.listDocuments()) == original_count
        )
        check("cancel preserves original geometry", document.getObject("Box").Length.Value == 10)
        selected["approve"] = True
        drive(commands.UpdateFromServerCommand())
        updated = App.ActiveDocument
        check(
            "updated geometry comes from other user's check-in",
            updated.getObject("Box").Length.Value == 25,
        )
        check(
            "update opens separate active copy",
            updated is not document and updated.FileName != old_path,
        )
        check(
            "original geometry and bytes preserved",
            document.getObject("Box").Length.Value == 10
            and workspace.digest(old_path)[0] == old_hash,
        )
        check("updated copy is clean", not cad.document_modified(updated))
        check(
            "updated exact dataset is recorded",
            not worker(alice.inspect_server_update, updated.FileName, item_id, revision_id)[
                "changed"
            ],
        )
        check("update does not acquire a checkout", worker(alice.get_checkout, revision_id) is None)
        count = len(worker(alice.list_datasets, revision_id))
        drive(commands.UpdateFromServerCommand())
        check("repeated check reports up-to-date", "already uses the latest" in messages[-1])
        check(
            "refresh does not publish datasets",
            len(worker(alice.list_datasets, revision_id)) == count,
        )
        updated.getObject("Box").Length = 30
        updated.recompute()
        try:
            drive(commands.UpdateFromServerCommand())
        except workspace.WorkspaceError:
            check(
                "unsaved edits block refresh and survive",
                updated.getObject("Box").Length.Value == 30,
            )
        else:
            raise AssertionError("Dirty document was allowed")
        check(
            "HTTP work stays off GUI thread", worker_threads and main_thread not in worker_threads
        )
        report["status"] = "passed"
    except BaseException as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        for name, function in originals.items():
            setattr(commands, name, function)
        for name in set(App.listDocuments()) - original_names:
            doc = App.getDocument(name)
            metadata = doc.getObject("ForgePDM_Metadata")
            if metadata:
                tree_observer.revoke_revision(metadata.RevisionId)
            App.closeDocument(name)
        session.Session.set_client(*previous_session)
        package.__path__ = previous_package_path
        if original_active:
            App.setActiveDocument(original_active)
        executor.shutdown(wait=True)
        check("user documents preserved", set(App.listDocuments()) == original_names)
        check(
            "user file hashes preserved",
            all(workspace.digest(p)[0] == h for p, h in original_files.items()),
        )
        (case / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
