"""Actual FreeCAD commands and isolated HTTP operations with injected transport loss."""


def run(App, Gui, directory):
    import json
    import sys
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path
    from threading import get_ident

    import freecad.forgepdm as package
    from freecad.forgepdm import (
        api,
        cad,
        commands,
        part_checkin,
        session,
        tree_observer,
        ui,
        workspace,
    )

    case = Path(directory)
    config = json.loads((case / "connection.json").read_text())
    previous_client, previous_user = session.Session.client, session.Session.user
    previous_documents = set(App.listDocuments())
    previous_active = App.ActiveDocument.Name if App.ActiveDocument else None
    originals = {
        name: getattr(commands, name)
        for name in ("ask_choice", "ask_text", "_choose_workspace", "information", "warning")
    }
    executor = ThreadPoolExecutor(max_workers=1)
    report = {
        "addon_version": package.__version__,
        "freecad": App.Version(),
        "python": sys.version,
        "qt": ui.QtCore.qVersion(),
        "checks": [],
        "scope": "Isolated HTTP database/storage/workspace; actual GUI commands; injected transport faults only",
    }
    main_thread = get_ident()
    worker_threads = []
    messages = []
    choice = {"restart": False, "kind": "part"}

    def check(label, value):
        assert value, label
        report["checks"].append(label)

    def worker(function, *args, **kwargs):
        def execute():
            worker_threads.append(get_ident())
            return function(*args, **kwargs)

        future = executor.submit(execute)
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
            try:
                value = worker(request.function, *request.args, **request.kwargs)
            except BaseException as error:
                # The real workflow engine throws worker failures back into the generator.
                try:
                    request = workflow.throw(error)
                except StopIteration:
                    return
                value = worker(request.function, *request.args, **request.kwargs)

    client = api.ForgePDMClient(config["base_url"])
    try:
        user = worker(client.login, config["username"], config["password"])
        session.Session.set_client(client, user)

        def choose(title, prompt, options, *args):
            if title == "New ForgePDM Item":
                return choice["kind"]
            if title == "Interrupted Check-in":
                return (
                    "Start new check-in from current document"
                    if choice["restart"]
                    else "Keep pending snapshot"
                )
            return options[0]

        commands.ask_choice = choose
        commands.ask_text = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Check-in unexpectedly asked for a note")
        )
        commands._choose_workspace = lambda *args: str(case / "working")
        commands.information = commands.warning = lambda title, text: messages.append(text)
        document = App.newDocument("AtomicCheckinFixture")
        box = document.addObject("Part::Box", "Box")
        box.Length = 10
        document.recompute()
        document.saveAs(str(case / "part.FCStd"))
        drive(commands.UploadCommand().action())
        metadata = document.getObject("ForgePDM_Metadata")
        revision_id = metadata.RevisionId
        path = Path(document.FileName)
        before = worker(client.list_datasets, revision_id)
        send = client.upload_part_checkin
        calls = []
        fault = {"mode": "lost"}

        def faulty(snapshot, operation):
            calls.append(operation["operation_id"])
            if fault["mode"] == "interrupted":
                fault["mode"] = None
                raise api.ForgePDMError("Injected interrupted transfer", code="connection_failed")
            result = send(snapshot, operation)
            if fault["mode"] == "lost":
                fault["mode"] = None
                raise api.ForgePDMError("Injected lost server response", code="connection_failed")
            return result

        client.upload_part_checkin = faulty
        try:
            drive(commands.CheckInCommand().action())
        except api.ForgePDMError as error:
            check(
                "lost response is surfaced without losing recovery journal",
                error.code == "connection_failed",
            )
        else:
            raise AssertionError("Lost response injection did not fail")
        pending = json.loads((path.parent / part_checkin.JOURNAL).read_text())
        first_key = pending["operation_id"]
        check(
            "server completed one dataset despite lost response",
            len(worker(client.list_datasets, revision_id)) == len(before) + 1,
        )
        check(
            "successful server transaction released checkout",
            worker(client.get_checkout, revision_id) is None,
        )
        check(
            "local pending journal contains original lease and snapshot",
            pending["state"] == "prepared"
            and (case / "working" / pending["snapshot_path"]).exists(),
        )
        saved_hash = workspace.digest(path)
        box.Length = 12
        document.recompute()
        drive(commands.CheckInCommand().action())
        check(
            "retry recovers committed result without uploading again",
            len(calls) == 1 and len(worker(client.list_datasets, revision_id)) == len(before) + 1,
        )
        check(
            "unsaved local edits survive recovery",
            box.Length.Value == 12
            and cad.document_modified(document)
            and workspace.digest(path) == saved_hash,
        )
        check(
            "user is told local edits were not included",
            any("Local edits remain" in text for text in messages),
        )
        check(
            "recovered ledger is bound to exact committed bytes",
            workspace.binding(path, client.base_url)["entry"]["working_hash"]
            == pending["content_hash"],
        )
        check(
            "recovery journal is acknowledged",
            json.loads((path.parent / part_checkin.JOURNAL).read_text())["state"] == "acknowledged",
        )
        drive(commands.CheckoutCommand().action())
        drive(commands.CheckInCommand().action())
        second = json.loads((path.parent / part_checkin.JOURNAL).read_text())
        check(
            "new checkout and explicit check-in create a distinct operation",
            second["operation_id"] != first_key
            and len(worker(client.list_datasets, revision_id)) == len(before) + 2,
        )
        check(
            "current document saves cleanly after normal atomic check-in",
            not cad.document_modified(document),
        )
        drive(commands.CheckInCommand().action())
        check(
            "repeated completed check-in does not duplicate datasets",
            len(worker(client.list_datasets, revision_id)) == len(before) + 2,
        )
        drive(commands.CheckoutCommand().action())
        box.Length = 14
        document.recompute()
        fault["mode"] = "interrupted"
        try:
            drive(commands.CheckInCommand().action())
        except api.ForgePDMError:
            pass
        else:
            raise AssertionError("Interrupted transfer was accepted")
        rejected = json.loads((path.parent / part_checkin.JOURNAL).read_text())
        check(
            "interrupted pre-commit transfer leaves checkout held and no dataset",
            worker(client.get_checkout, revision_id) is not None
            and len(worker(client.list_datasets, revision_id)) == len(before) + 2,
        )
        worker(client.renew_checkout, revision_id)
        drive(commands.CheckInCommand().action())
        check(
            "renewed lease rejects original pending operation without new data",
            json.loads((path.parent / part_checkin.JOURNAL).read_text())["operation_id"]
            == rejected["operation_id"]
            and len(worker(client.list_datasets, revision_id)) == len(before) + 2,
        )
        box.Length = 16
        document.recompute()
        choice["restart"] = True
        drive(commands.CheckInCommand().action())
        final = json.loads((path.parent / part_checkin.JOURNAL).read_text())
        check(
            "explicit restart archives old snapshot and commits current bytes",
            final["operation_id"] != rejected["operation_id"]
            and (path.parent / ("part-checkin-" + rejected["operation_id"] + ".json")).exists()
            and box.Length.Value == 16,
        )
        check(
            "rejected old operation has no server completion record",
            worker(client.part_checkin_status, revision_id, rejected["operation_id"]) is None,
        )
        check(
            "only accepted operations produced native datasets",
            len(worker(client.list_datasets, revision_id)) == len(before) + 3,
        )
        check(
            "accepted snapshot bytes match current saved file",
            workspace.digest(path)[0] == final["content_hash"],
        )
        check(
            "final checkout released and document clean",
            worker(client.get_checkout, revision_id) is None
            and not cad.document_modified(document),
        )
        check(
            "completed old operation remains queryable",
            worker(client.part_checkin_status, revision_id, first_key)["status"] == "completed",
        )
        check(
            "all HTTP and file transfer operations stayed on workers",
            all(thread != main_thread for thread in worker_threads),
        )
        journal_text = (path.parent / part_checkin.JOURNAL).read_text()
        check(
            "journal contains no password or bearer token",
            config["password"] not in journal_text and client.token not in journal_text,
        )
        # Publish an assembly and a parent with repeated external subassembly links.
        choice["kind"] = "assembly"
        sub = App.newDocument("AtomicSubassemblyFixture")
        sub.saveAs(str(case / "subassembly.FCStd"))
        group = sub.addObject("Assembly::AssemblyObject", "Assembly")
        link = sub.addObject("App::Link", "PartLink")
        link.setLink(box)
        group.addObject(link)
        sub.recompute()
        sub.saveAs(str(case / "subassembly.FCStd"))
        drive(commands.UploadCommand().action())
        drive(commands.CheckInCommand().action())
        sub_meta = sub.getObject("ForgePDM_Metadata")
        sub_journal = json.loads((Path(sub.FileName).parent / part_checkin.JOURNAL).read_text())
        check(
            "subassembly atomic check-in retains exact part dataset pin",
            len(sub_journal["references"]) == 1
            and sub_journal["references"][0]["target_dataset_id"]
            == final["result"]["dataset"]["id"],
        )
        parent = App.newDocument("AtomicParentFixture")
        parent.saveAs(str(case / "parent.FCStd"))
        parent_group = parent.addObject("Assembly::AssemblyObject", "Assembly")
        for name in ("SubassemblyOne", "SubassemblyTwo"):
            occurrence = parent.addObject("Assembly::AssemblyLink", name)
            occurrence.LinkedObject = group
            parent_group.addObject(occurrence)
        parent.recompute()
        parent.saveAs(str(case / "parent.FCStd"))
        drive(commands.UploadCommand().action())
        parent_meta = parent.getObject("ForgePDM_Metadata")
        parent_revision = parent_meta.RevisionId
        parent_before = worker(client.list_datasets, parent_revision)
        fault["mode"] = "lost"
        try:
            drive(commands.CheckInCommand().action())
        except api.ForgePDMError as error:
            check(
                "assembly lost response leaves recoverable operation",
                error.code == "connection_failed",
            )
        else:
            raise AssertionError("Assembly lost-response injection did not fail")
        parent_path = Path(parent.FileName)
        pending_parent = json.loads((parent_path.parent / part_checkin.JOURNAL).read_text())
        check(
            "repeated subassembly occurrences retain exact original pins",
            {"SubassemblyOne", "SubassemblyTwo"}.issubset(
                {ref["object_name"] for ref in pending_parent["references"]}
            )
            and all(
                ref["target_revision_id"] == sub_meta.RevisionId
                and ref["target_dataset_id"] == sub_journal["result"]["dataset"]["id"]
                for ref in pending_parent["references"]
            ),
        )
        parent_group.Label = "Local unsaved assembly edit"
        parent.recompute()
        drive(commands.CheckInCommand().action())
        acknowledged = json.loads((parent_path.parent / part_checkin.JOURNAL).read_text())
        check(
            "assembly retry publishes no duplicate and preserves unsaved edits",
            len(worker(client.list_datasets, parent_revision)) == len(parent_before) + 1
            and parent_group.Label == "Local unsaved assembly edit"
            and cad.document_modified(parent),
        )
        manifest = worker(client.get_manifest, acknowledged["result"]["dataset"]["id"])
        check(
            "server assembly manifest and recovered ledger match recorded pins",
            manifest["references"] == pending_parent["references"]
            and workspace.binding(parent_path, client.base_url)["entry"]["references"]
            == manifest["references"],
        )
        check(
            "assembly check-in releases only the parent lease",
            worker(client.get_checkout, parent_revision) is None,
        )
        report["status"] = "passed"
    except BaseException as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        for name, function in originals.items():
            setattr(commands, name, function)
        for name in set(App.listDocuments()) - previous_documents:
            document = App.getDocument(name)
            metadata = document.getObject("ForgePDM_Metadata")
            if metadata:
                tree_observer.revoke_revision(metadata.RevisionId)
            App.closeDocument(name)
        session.Session.set_client(previous_client, previous_user)
        if previous_active:
            App.setActiveDocument(previous_active)
        executor.shutdown(wait=True)
        (case / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
