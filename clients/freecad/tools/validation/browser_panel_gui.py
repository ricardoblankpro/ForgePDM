"""Persistent browser acceptance with disposable native CAD and real authorized HTTP."""


def run(App, Gui, directory):
    import hashlib
    import importlib.util
    import json
    import secrets
    import time
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path
    from uuid import uuid4

    from freecad.forgepdm import (
        api,
        browser_panel,
        cad,
        commands,
        session,
        settings,
        tree_observer,
        ui,
        workspace,
    )
    from freecad.forgepdm.browser_library import BrowserLibrary

    case = Path(directory)
    original_session = session.Session.client, session.Session.user
    original_active = App.ActiveDocument.Name if App.ActiveDocument else None

    def documents():
        return {
            d.Name: (
                d.FileName,
                cad.document_modified(d),
                workspace.digest(d.FileName) if d.FileName else None,
            )
            for d in App.listDocuments().values()
        }

    original_documents = documents()
    # Reuse the existing 28-check native assembly/part publication fixture.
    spec = importlib.util.spec_from_file_location(
        "panel_atomic_fixture",
        Path(__file__).parents[2] / "tests/freecad_atomic_checkin_integration.py",
    )
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    fixture.run(App, Gui, str(case))
    config = json.loads((case / "connection.json").read_text())
    executor = ThreadPoolExecutor(max_workers=1)
    accounts = []
    checks = []
    report = {
        "checks": checks,
        "scope": "Disposable HTTP/CAD fixture; persistent Qt dock and real task workflows",
        "freecad": App.Version(),
        "qt": ui.QtCore.qVersion(),
        "commands_module": commands.__file__,
    }
    root = case / "panel-workspace"
    root.mkdir(exist_ok=True)

    def wait(predicate, timeout=30):
        deadline = time.monotonic() + timeout
        loop = ui.QtCore.QEventLoop()
        timer = ui.QtCore.QTimer()
        errors = []

        def tick():
            try:
                if predicate():
                    loop.quit()
                elif time.monotonic() > deadline:
                    errors.append(AssertionError("Native browser event loop timed out"))
                    loop.quit()
            except BaseException as error:
                errors.append(error)
                loop.quit()

        timer.timeout.connect(tick)
        timer.start(10)
        if not predicate():
            loop.exec()
        timer.stop()
        if errors:
            raise errors[0]

    def worker(function, *args, **kwargs):
        future = executor.submit(function, *args, **kwargs)
        wait(future.done)
        return future.result()

    def drive(workflow):
        value = None
        while True:
            try:
                request = workflow.send(value)
            except StopIteration:
                return
            value = worker(request.function, *request.args, **request.kwargs)

    def check(label, condition):
        assert condition, label
        checks.append(label)

    def panel(client, user):
        session.Session.set_client(client, user)
        drive(commands.DownloadCommand().action())
        dock = browser_panel._dock
        wait(lambda: dock.view.open_button.isEnabled() or not dock.view.jobs)
        return dock

    def open_selected(view):
        selection = dict(view.item) if view.item else None
        view.request_open()
        job = view.open_job
        assert job is not None, (selection, view.status.text())
        wait(lambda: job.done and view.open_job is None and not session.Session.busy)
        if job.error:
            raise job.error
        return App.ActiveDocument

    try:
        client = api.ForgePDMClient(config["base_url"])
        user = worker(client.login, config["username"], config["password"])
        accounts.append((client.base_url, user["id"]))
        settings.save_workspace(str(root), client.base_url, user["id"])
        item = worker(client.search_items, "", number_series="A")["items"][0]
        expected = worker(client.list_datasets, item["current_revision_id"])
        dock = panel(client, user)
        view = dock.view
        view.query.setText(item["number"])
        wait(
            lambda: (
                view.item is not None
                and view.item["id"] == item["id"]
                and view.open_button.isEnabled()
            )
        )
        check(
            "Name column removed from live dock",
            [view.results.headerItem().text(i) for i in range(view.results.columnCount())]
            == ["Item", "Description", "Revision", "Lifecycle"],
        )
        check(
            "browser is modeless and leaves CAD usable",
            dock.isVisible() and not session.Session.busy and not view.isModal(),
        )
        view.favorite.click()
        check(
            "favorite saves only the item ID for this account",
            BrowserLibrary(client.base_url, user["id"]).load()["favorites"] == [item["id"]],
        )
        view.source.setCurrentIndex(2)
        wait(lambda: not view.jobs and view.open_button.isEnabled())
        check("Favorites resolves current authorized metadata", view.item["id"] == item["id"])
        latest = open_selected(view)
        binding = workspace.binding(latest.FileName, client.base_url)
        pins = worker(client.get_manifest, binding["entry"]["dataset_id"])["references"]
        check(
            "opening from persistent panel keeps exact assembly pins",
            binding["entry"]["references"] == pins,
        )
        check("panel stays available after opening", dock.isVisible() and view.isEnabled())
        history = BrowserLibrary(client.base_url, user["id"]).load()["recent"]
        check(
            "successful open records exact revision dataset and file",
            len(history) == 1
            and history[0]["file_id"] == binding["entry"]["file_id"]
            and history[0]["revision_id"] == item["current_revision_id"],
        )
        view.source.setCurrentIndex(1)
        wait(lambda: not view.jobs and view.open_button.isEnabled())
        check(
            "Recent restores exact recorded snapshot",
            view.snapshot.currentData()[1]["id"] == history[0]["file_id"],
        )
        view.snapshot.setCurrentIndex(view.snapshot.count() - 1)
        older = open_selected(view)
        older_binding = workspace.binding(older.FileName, client.base_url)
        check(
            "older snapshot opens separately and becomes newest recent",
            older is not latest
            and BrowserLibrary(client.base_url, user["id"]).load()["recent"][0]["file_id"]
            == older_binding["entry"]["file_id"],
        )
        older.Label = "Unsaved panel acceptance edit"
        before = set(App.listDocuments())
        saved = workspace.digest(older.FileName)
        wait(lambda: not view.jobs and view.open_button.isEnabled())
        reopened = open_selected(view)
        check(
            "reopening Recent preserves dirty document without duplicates",
            reopened is older
            and set(App.listDocuments()) == before
            and cad.document_modified(older)
            and older.Label == "Unsaved panel acceptance edit"
            and workspace.digest(older.FileName) == saved,
        )
        check(
            "opening does not create datasets or acquire checkout",
            len(worker(client.list_datasets, item["current_revision_id"])) == len(expected)
            and worker(client.get_checkout, item["current_revision_id"]) is None,
        )
        dock.hide()
        drive(commands.DownloadCommand().action())
        check(
            "toolbar action reuses hidden panel", browser_panel._dock is dock and dock.isVisible()
        )
        # Explicit fixture edit action: validate My Checkouts against actual ownership.
        worker(client.acquire_checkout, item["current_revision_id"])
        view.query.clear()
        view.source.setCurrentIndex(3)
        wait(lambda: not view.jobs and view.results.topLevelItemCount() > 0)
        rows = [
            view.results.topLevelItem(i).data(0, ui.QtCore.Qt.UserRole)
            for i in range(view.results.topLevelItemCount())
        ]
        check(
            "My Checkouts comes from authenticated server leases",
            any(row["id"] == item["id"] and row["checkout_status"] == "active" for row in rows),
        )
        dock.grab().save(str(case / "browser-panel.png"))
        username = "panel-viewer-" + uuid4().hex[:8]
        password = secrets.token_urlsafe(20)
        worker(
            client._json_request,
            "POST",
            "/api/v1/admin/users",
            {
                "username": username,
                "display_name": "Panel isolated viewer",
                "password": password,
                "role": "user",
            },
        )
        other = api.ForgePDMClient(config["base_url"])
        other_user = worker(other.login, username, password)
        accounts.append((other.base_url, other_user["id"]))
        session.Session.set_client(other, other_user)
        check(
            "account switch immediately hides and clears prior panel",
            not dock.isVisible() and view.results.topLevelItemCount() == 0,
        )
        other_dock = panel(other, other_user)
        other_view = other_dock.view
        other_view.source.setCurrentIndex(2)
        wait(lambda: not other_view.jobs)
        check(
            "new account cannot see previous favorites or recent IDs",
            other_view.results.topLevelItemCount() == 0
            and BrowserLibrary(other.base_url, other_user["id"]).load()
            == {"favorites": [], "recent": []},
        )
        BrowserLibrary(other.base_url, other_user["id"]).toggle_favorite(item["id"])
        other_view.search()
        wait(lambda: not other_view.jobs)
        check(
            "saved inaccessible IDs are resolved again and omitted",
            other_view.results.topLevelItemCount() == 0
            and "unavailable" in other_view.results.toolTip(),
        )
        # A new HTTP client for the original user reuses local preferences.
        fresh = api.ForgePDMClient(config["base_url"])
        fresh_user = worker(fresh.login, config["username"], config["password"])
        fresh_dock = panel(fresh, fresh_user)
        fresh_dock.view.source.setCurrentIndex(2)
        wait(lambda: not fresh_dock.view.jobs and fresh_dock.view.open_button.isEnabled())
        check(
            "favorites survive a fresh authenticated client",
            fresh_dock.view.item["id"] == item["id"],
        )
        fresh_dock.grab().save(str(case / "browser-panel-favorites.png"))
        report["status"] = "passed"
    except BaseException as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        dock = browser_panel._dock
        session.Session.clear()
        if dock:
            wait(lambda: not dock.view.jobs and dock.view.open_job is None)
        for name in set(App.listDocuments()) - set(original_documents):
            document = App.getDocument(name)
            metadata = document.getObject("ForgePDM_Metadata")
            if metadata:
                tree_observer.revoke_revision(metadata.RevisionId)
            App.closeDocument(name)
        for server, actor in accounts:
            key = hashlib.sha256((server + "\n" + actor).encode()).hexdigest()
            settings._parameters().GetGroup("Workspaces").RemGroup(key)
        session.Session.set_client(*original_session)
        if original_active:
            App.setActiveDocument(original_active)
        executor.shutdown(wait=True)
        report["original_documents_preserved"] = documents() == original_documents
        report["original_document_count"] = len(original_documents)
        (case / "panel-report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
