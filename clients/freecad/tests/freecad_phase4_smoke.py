"""Isolated real-FreeCAD integration harness, invoked through the local MCP.

Start its disposable backend with `uv run python <this file> --serve CASE_DIR`.
Then execute `run(App, Gui, CASE_DIR)` in the GUI process through MCP.
"""


def serve(case):
    import json
    import os
    from pathlib import Path
    import secrets
    import socket
    from datetime import datetime, timezone
    from uuid import uuid4

    import uvicorn

    case = Path(case)
    case.mkdir(parents=True, exist_ok=False)
    os.environ["FORGEPDM_DATABASE"] = str(case / "metadata.sqlite3")
    os.environ["FORGEPDM_FILE_ROOT"] = str(case / "files")
    from forgepdm.main import create_app
    from forgepdm.application.auth import hash_password

    app = create_app()
    password = secrets.token_urlsafe(24)
    with app.state.database.transaction() as connection:
        connection.execute(
            "INSERT INTO users(id,username,display_name,enabled,created_at,password_hash,role) "
            "VALUES (?, 'phase4', 'Phase 4 test', 1, ?, ?, 'admin')",
            (str(uuid4()), datetime.now(timezone.utc).isoformat(), hash_password(password)),
        )
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    config = case / "connection.json"
    config.write_text(
        json.dumps(
            {
                "base_url": "http://127.0.0.1:" + str(listener.getsockname()[1]),
                "username": "phase4",
                "password": password,
            }
        )
    )
    config.chmod(0o600)
    uvicorn.Server(uvicorn.Config(app, log_level="warning")).run(sockets=[listener])


def run(App, Gui, case_directory):
    from concurrent.futures import ThreadPoolExecutor
    import importlib
    import json
    from pathlib import Path
    import sys
    from threading import get_ident

    import freecad.forgepdm as package

    source = Path(__file__).resolve().parents[1] / "freecad/forgepdm"
    previous_path = list(package.__path__)
    package.__path__ = [str(source)]
    from freecad.forgepdm import api, bom, cad, commands, session, ui, workspace

    for module in (workspace, api, cad, bom, ui, commands):
        importlib.reload(module)
    original_client, original_user = session.Session.client, session.Session.user
    originals = {
        name: getattr(commands, name)
        for name in ("information", "select_bom_occurrences", "review_bom")
    }
    names = set(App.listDocuments())
    active = App.ActiveDocument.Name if App.ActiveDocument else None
    case = Path(case_directory)
    config = json.loads((case / "connection.json").read_text())
    report = {
        "freecad": App.Version(),
        "python": sys.version,
        "qt": ui.QtCore.qVersion(),
        "checks": [],
        "scope": "Real GUI adapters/dialogs, isolated HTTP backend, disposable documents",
    }
    main_thread = get_ident()
    worker_threads = []
    executor = ThreadPoolExecutor(max_workers=1)

    def check(name, result):
        assert result, name
        report["checks"].append(name)

    def worker(function, *args, **kwargs):
        def call():
            worker_threads.append(get_ident())
            return function(*args, **kwargs)

        future = executor.submit(call)
        loop = ui.QtCore.QEventLoop()
        timer = ui.QtCore.QTimer()
        timer.timeout.connect(lambda: loop.quit() if future.done() else None)
        timer.start(5)
        if not future.done():
            loop.exec()
        timer.stop()
        return future.result(timeout=1)

    def drive(generator):
        value = None
        while True:
            try:
                request = generator.send(value)
            except StopIteration:
                return
            value = worker(request.function, *request.args, **request.kwargs)

    client = api.ForgePDMClient(config["base_url"])

    def upload(document, kind):
        item = worker(client.create_item, kind, document.Label)
        path = worker(workspace.prepare_working, client.base_url, str(case / "workspace"))
        commands._set_metadata(
            document,
            ItemId=item["id"],
            RevisionId=item["current_revision_id"],
            ItemNumber=item["number"],
            RevisionLabel="A",
            ServerUrl=client.base_url,
        )
        document.recompute()
        document.saveAs(path)
        cad.rebase_links(document)
        commands._save_document(document)
        worker(
            client.upload_native,
            path,
            item["current_revision_id"],
            item["id"],
            cad.capture(document),
        )
        return item

    def automate_selection(references):
        def choose():
            dialog = ui.QtWidgets.QApplication.activeModalWidget()
            if dialog is None:
                return
            for widget in dialog.findChildren(ui.QtWidgets.QCheckBox):
                widget.setChecked(True)
            dialog.accept()

        ui.QtCore.QTimer.singleShot(50, choose)
        return ui.select_bom_occurrences(references)

    def automate_review(current, proposal):
        def approve():
            dialog = ui.QtWidgets.QApplication.activeModalWidget()
            boxes = dialog.findChildren(ui.QtWidgets.QCheckBox)
            buttons = dialog.findChild(ui.QtWidgets.QDialogButtonBox)
            check(
                "replacement disabled until explicit consent",
                not buttons.button(ui.QtWidgets.QDialogButtonBox.Ok).isEnabled(),
            )
            boxes[0].setChecked(True)
            check(
                "replacement enabled after consent",
                buttons.button(ui.QtWidgets.QDialogButtonBox.Ok).isEnabled(),
            )
            dialog.accept()

        ui.QtCore.QTimer.singleShot(50, approve)
        return ui.review_bom(current, proposal)

    try:
        user = worker(client.login, config["username"], config["password"])
        session.Session.set_client(client, user)
        commands.information = lambda *args: None
        commands.select_bom_occurrences = automate_selection
        commands.review_bom = automate_review
        child = App.newDocument("Phase4Child")
        box = child.addObject("Part::Box", "Box")
        child_item = upload(child, "part")
        sub = App.newDocument("Phase4Sub")
        sub.saveAs(str(case / "sub-source.FCStd"))
        group = sub.addObject("App::Part", "Assembly")
        first = sub.addObject("App::Link", "First")
        first.setLink(box)
        group.addObject(first)
        repeat = sub.addObject("App::Link", "Repeat")
        repeat.setLink(first)
        group.addObject(repeat)
        repeat.Placement.Base = App.Vector(25, 0, 0)
        sub_item = upload(sub, "assembly")
        App.setActiveDocument(sub.Name)
        drive(commands._synchronize_bom(client, sub_item["current_revision_id"]))
        lines = worker(client.get_bom, sub_item["current_revision_id"])
        check(
            "external plus internal repeated occurrence quantity is two",
            len(lines) == 1
            and lines[0]["quantity"] == "2"
            and lines[0]["component_revision_id"] == child_item["current_revision_id"],
        )
        check("occurrence placements unchanged", repeat.Placement.Base.x == 25)

        root = App.newDocument("Phase4Root")
        root.saveAs(str(case / "root-source.FCStd"))
        link = root.addObject("App::Link", "Nested")
        link.setLink(group)
        root_item = upload(root, "assembly")
        App.setActiveDocument(root.Name)

        def open_synchronization():
            dialog = ui.QtWidgets.QApplication.activeModalWidget()
            if dialog and dialog.windowTitle().startswith("ForgePDM BOM"):
                for button in dialog.findChildren(ui.QtWidgets.QPushButton):
                    if button.text().startswith("Synchronize from CAD"):
                        launcher.stop()
                        button.click()

        launcher = ui.QtCore.QTimer()
        launcher.timeout.connect(open_synchronization)
        launcher.start(10)
        try:
            drive(commands.ShowBOMCommand().action())
        finally:
            launcher.stop()
        lines = worker(client.get_bom, root_item["current_revision_id"])
        check(
            "nested assembly remains a single direct component",
            len(lines) == 1
            and lines[0]["quantity"] == "1"
            and lines[0]["component_revision_id"] == sub_item["current_revision_id"],
        )

        before = worker(client.get_bom, root_item["current_revision_id"])
        commands.review_bom = lambda *args: False
        drive(commands._synchronize_bom(client, root_item["current_revision_id"]))
        check(
            "canceling review preserves existing BOM",
            worker(client.get_bom, root_item["current_revision_id"]) == before,
        )
        worker(client.checkin, child_item["current_revision_id"], "Release component A")
        worker(client.transition, child_item["current_revision_id"], "released")
        newer = worker(client.create_next_revision, child_item["id"], "Create B")
        check(
            "component has a newer current revision",
            newer["id"] != child_item["current_revision_id"],
        )
        App.setActiveDocument(sub.Name)
        commands.review_bom = automate_review
        drive(commands._synchronize_bom(client, sub_item["current_revision_id"]))
        historical = worker(client.get_bom, sub_item["current_revision_id"])
        check(
            "resynchronization retains historical revision A after B exists",
            historical[0]["component_revision_id"] == child_item["current_revision_id"],
        )
        App.setActiveDocument(root.Name)

        def change_during_review(current, proposal):
            link.Placement.Base = App.Vector(75, 0, 0)
            root.recompute()
            return True

        commands.review_bom = change_during_review
        try:
            drive(commands._synchronize_bom(client, root_item["current_revision_id"]))
        except RuntimeError as error:
            check(
                "CAD mutation during review blocks synchronization",
                "changed during review" in str(error),
            )
        else:
            raise AssertionError("changed CAD accepted")
        check(
            "CAD mutation leaves server BOM unchanged",
            worker(client.get_bom, root_item["current_revision_id"]) == before,
        )
        first.ElementCount = 2
        sub.recompute()
        try:
            cad.capture_bom(sub)
        except workspace.WorkspaceError:
            check("real FreeCAD link arrays are rejected", True)
        else:
            raise AssertionError("link array accepted")
        snapshot = worker(client.bom_snapshot, root_item["current_revision_id"])
        worker(client.synchronize_bom, root_item["current_revision_id"], [], snapshot)
        try:
            worker(client.synchronize_bom, root_item["current_revision_id"], [], snapshot)
        except api.ForgePDMError as error:
            check("stale review rejected by HTTP transaction", error.status == 409)
        else:
            raise AssertionError("stale review accepted")
        check(
            "all HTTP work stayed off GUI thread",
            all(thread != main_thread for thread in worker_threads),
        )
        report["status"] = "passed"
    except BaseException:
        report["status"] = "failed"
        raise
    finally:
        for key, value in originals.items():
            setattr(commands, key, value)
        session.Session.client, session.Session.user = original_client, original_user
        for name in set(App.listDocuments()) - names:
            App.closeDocument(name)
        if active:
            App.setActiveDocument(active)
        executor.shutdown(wait=True)
        package.__path__ = previous_path
        (case / "report.json").write_text(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", required=True)
    serve(parser.parse_args().serve)
