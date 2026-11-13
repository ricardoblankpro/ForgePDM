"""Native revision-command recovery and fenced legacy HTTP against disposable data."""


def run(App, Gui, directory):
    import json
    import os
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path
    from threading import get_ident

    from freecad.forgepdm import api, cad, commands, session, tree_observer, ui, workspace

    case = Path(directory)
    config = json.loads((case / "connection.json").read_text())
    previous_session = session.Session.client, session.Session.user
    previous_active = App.ActiveDocument.Name if App.ActiveDocument else None
    previous_documents = {
        d.Name: (d.FileName, cad.document_modified(d)) for d in App.listDocuments().values()
    }
    original_ui = {
        name: getattr(commands, name)
        for name in ("ask_choice", "ask_text", "_choose_workspace", "information", "warning")
    }
    old_state = os.environ.get("XDG_STATE_HOME")
    os.environ["XDG_STATE_HOME"] = str(case / "revision-state")
    executor = ThreadPoolExecutor(max_workers=1)
    main_thread = get_ident()
    checks, threads = [], []
    report = {
        "freecad": App.Version(),
        "qt": ui.QtCore.qVersion(),
        "scope": "Disposable backend, CAD and local state; real native commands and worker HTTP",
        "checks": checks,
    }

    def check(label, condition):
        assert condition, label
        checks.append(label)

    def worker(function, *args, **kwargs):
        def execute():
            threads.append(get_ident())
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
        pending_error = None
        while True:
            try:
                request = workflow.throw(pending_error) if pending_error else workflow.send(value)
            except StopIteration:
                return
            pending_error = None
            try:
                value = worker(request.function, *request.args, **request.kwargs)
            except BaseException as error:
                pending_error = error

    try:
        client = api.ForgePDMClient(config["base_url"])
        user = worker(client.login, config["username"], config["password"])
        session.Session.set_client(client, user)
        commands.ask_choice = lambda title, prompt, options, *args: (
            "part" if title == "New ForgePDM Item" else options[0]
        )
        commands.ask_text = lambda *args: "Phase 5 next revision"
        commands._choose_workspace = lambda *args: str(case / "revision-working")
        commands.information = commands.warning = lambda *args: None
        source = App.newDocument("Phase5RevisionSource")
        box = source.addObject("Part::Box", "Box")
        box.Length = 19
        source.recompute()
        source.saveAs(str(case / "revision-source.FCStd"))
        drive(commands.UploadCommand().action())
        metadata = source.getObject("ForgePDM_Metadata")
        item_id, source_id, source_path = metadata.ItemId, metadata.RevisionId, source.FileName
        drive(commands.CheckInCommand().action())
        drive(commands.ReleaseCommand().action())
        source_hash = workspace.digest(source_path)
        send = client._json_request
        lost = []

        def fault(method, path, payload=None, **kwargs):
            result = send(method, path, payload, **kwargs)
            if method == "POST" and path.endswith("/revisions/recoverable") and not lost:
                lost.append(payload["operation_id"])
                raise api.ForgePDMError("Injected lost revision response", code="connection_failed")
            return result

        client._json_request = fault
        try:
            drive(commands.NewRevisionCommand().action())
        except api.ForgePDMError as error:
            check("lost revision response is reported", error.code == "connection_failed")
        else:
            raise AssertionError("fault did not fire")
        revisions = worker(client.list_revisions, item_id)
        # Catalog revisions are paginated.
        revisions = revisions.get("items", revisions) if isinstance(revisions, dict) else revisions
        check("one next revision exists after lost response", len(revisions) == 2)
        check(
            "source file and live identity survive failed adoption",
            metadata.RevisionId == source_id
            and workspace.digest(source_path) == source_hash
            and not cad.document_modified(source),
        )
        journals = list((case / "revision-state").rglob("operation.json"))
        check(
            "pending journal retains prepared CAD copy",
            len(journals) == 1
            and Path(json.loads(journals[0].read_text())["working_copy_path"]).is_file(),
        )
        fresh = api.ForgePDMClient(config["base_url"])
        worker(fresh.login, config["username"], config["password"])
        session.Session.set_client(fresh, user)
        commands.ask_text = lambda *args: (_ for _ in ()).throw(
            AssertionError("recovery prompted for a new note")
        )
        App.setActiveDocument(source.Name)
        drive(commands.NewRevisionCommand().action())
        target = App.ActiveDocument
        target_meta = target.getObject("ForgePDM_Metadata")
        check(
            "fresh client recovers original revision into separate document",
            target.Name != source.Name
            and target_meta.RevisionId != source_id
            and target_meta.RevisionLabel == "B",
        )
        check(
            "original revision retains identity geometry and bytes",
            metadata.RevisionId == source_id
            and box.Length.Value == 19
            and workspace.digest(source_path) == source_hash,
        )
        datasets = worker(fresh.list_datasets, target_meta.RevisionId)
        check(
            "recovered copy uploads once with exact manifest",
            len(datasets) == 1
            and worker(fresh.get_manifest, datasets[0]["id"])["references"] == [],
        )
        check(
            "server creates one operation and one next revision",
            len(worker(fresh.list_revisions, item_id)["items"]) == 2,
        )
        target.getObject("Box").Length = 23
        target.recompute()
        App.setActiveDocument(source.Name)
        try:
            drive(commands.NewRevisionCommand().action())
        except workspace.WorkspaceError as error:
            check(
                "recovery preserves an already open dirty target",
                "already open with edits" in str(error)
                and target.getObject("Box").Length.Value == 23
                and cad.document_modified(target),
            )
        else:
            raise AssertionError("dirty target was not guarded")
        # Use saved, unchanged fixture bytes for ordinary legacy upload fencing.
        original_multipart = fresh._multipart_file

        def renew_during_request(endpoint, path, fields):
            fresh.renew_checkout(target_meta.RevisionId)
            return original_multipart(endpoint, path, fields)

        fresh._multipart_file = renew_during_request
        try:
            worker(fresh.upload_file, target_meta.RevisionId, target.FileName)
        except api.ForgePDMError as error:
            check("native HTTP upload rejects renewed token", error.status == 409)
        else:
            raise AssertionError("stale upload committed")
        fresh._multipart_file = original_multipart
        check(
            "stale native upload creates no dataset",
            len(worker(fresh.list_datasets, target_meta.RevisionId)) == 1,
        )
        dataset = worker(fresh.upload_file, target_meta.RevisionId, target.FileName)
        worker(fresh.renew_checkout, target_meta.RevisionId)
        try:
            worker(fresh.attach_manifest, dataset["id"], dataset["files"][0]["id"], [])
        except api.ForgePDMError as error:
            check("manifest uses original upload token and rejects renewal", error.status == 409)
        else:
            raise AssertionError("stale manifest committed")
        check("all HTTP ran on worker thread", bool(threads) and main_thread not in threads)
        report["status"] = "passed"
    except BaseException as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        for name, value in original_ui.items():
            setattr(commands, name, value)
        for name in set(App.listDocuments()) - set(previous_documents):
            doc = App.getDocument(name)
            metadata = doc.getObject("ForgePDM_Metadata")
            if metadata:
                tree_observer.revoke_revision(metadata.RevisionId)
            App.closeDocument(name)
        session.Session.set_client(*previous_session)
        if previous_active:
            App.setActiveDocument(previous_active)
        if old_state is None:
            os.environ.pop("XDG_STATE_HOME", None)
        else:
            os.environ["XDG_STATE_HOME"] = old_state
        executor.shutdown(wait=True)
        report["existing_documents_preserved"] = previous_documents == {
            d.Name: (d.FileName, cad.document_modified(d)) for d in App.listDocuments().values()
        }
        (case / "revision-report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
