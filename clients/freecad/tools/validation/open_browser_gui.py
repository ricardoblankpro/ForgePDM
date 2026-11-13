"""Real FreeCAD Open browser, retrieval and dirty exact-snapshot reactivation."""


def run(App, Gui, directory):
    import hashlib
    import importlib.util
    import json
    import time
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path

    from freecad import forgepdm as package
    from freecad.forgepdm import api, cad, commands, session, settings, tree_observer, ui, workspace
    from freecad.forgepdm.open_ui import OpenDialog

    case = Path(directory)
    # Seed disposable native part/AssemblyLink data using the existing full protocol fixture.
    spec = importlib.util.spec_from_file_location(
        "open_atomic_fixture",
        Path(__file__).parents[2] / "tests/freecad_atomic_checkin_integration.py",
    )
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    fixture.run(App, Gui, str(case))
    config = json.loads((case / "connection.json").read_text())
    before_session = session.Session.client, session.Session.user
    before_docs = {
        d.Name: (d.FileName, cad.document_modified(d)) for d in App.listDocuments().values()
    }
    before_active = App.ActiveDocument.Name if App.ActiveDocument else None
    original_dialog, original_choose = commands.execute_dialog, commands._choose_workspace
    executor = ThreadPoolExecutor(max_workers=1)
    checks = []
    report = {
        "checks": checks,
        "freecad": App.Version(),
        "qt": ui.QtCore.qVersion(),
        "scope": "Disposable HTTP/CAD data; real modal browser and native reconstruction",
        "addon": package.__version__,
        "commands_module": commands.__file__,
    }
    client = api.ForgePDMClient(config["base_url"])
    user = None
    root = case / "open-workspace"
    root.mkdir(exist_ok=True)
    mode = {"older": False}
    selected = []
    picker_calls = []

    def check(label, condition):
        assert condition, label
        checks.append(label)

    def worker(function, *args, **kwargs):
        future = executor.submit(function, *args, **kwargs)
        loop = ui.QtCore.QEventLoop()
        timer = ui.QtCore.QTimer()
        timer.timeout.connect(lambda: loop.quit() if future.done() else None)
        timer.start(5)
        if not future.done():
            loop.exec()
        timer.stop()
        return future.result()

    def drive(workflow):
        value = None
        while True:
            try:
                request = workflow.send(value)
            except StopIteration:
                return
            value = worker(request.function, *request.args, **request.kwargs)

    try:
        user = worker(client.login, config["username"], config["password"])
        session.Session.set_client(client, user)
        settings.save_workspace(str(root), client.base_url, user["id"])
        items = worker(client.search_items, "", number_series="A")["items"]
        item = items[0]
        expected = worker(client.list_datasets, item["current_revision_id"])
        expected = sorted(
            (d for d in expected if d["dataset_type"] == "native_cad"),
            key=lambda d: d["created_at"],
            reverse=True,
        )
        check("native assembly fixture has multiple exact snapshots", len(expected) > 1)

        def choose(*args, **kwargs):
            picker_calls.append(True)
            raise AssertionError("Workspace picker must not appear for configured root")

        commands._choose_workspace = choose

        def automate(dialog):
            assert isinstance(dialog, OpenDialog)
            dialog.query.setText(item["number"])
            deadline = time.monotonic() + 30
            errors = []

            def act():
                try:
                    if time.monotonic() > deadline:
                        raise AssertionError(dialog.status.text())
                    if (
                        not dialog.item
                        or dialog.item["id"] != item["id"]
                        or not dialog.open_button.isEnabled()
                    ):
                        return
                    if mode["older"]:
                        dialog.snapshot.setCurrentIndex(dialog.snapshot.count() - 1)
                    timer.stop()
                    dialog.grab().save(str(case / "open-browser.png"))
                    dialog.request_open()
                    selected.append(dialog.selection)
                except BaseException as error:
                    errors.append(error)
                    timer.stop()
                    dialog.reject()

            timer = ui.QtCore.QTimer(dialog)
            timer.timeout.connect(act)
            timer.start(25)
            result = original_dialog(dialog)
            timer.stop()
            if errors:
                raise errors[0]
            return result

        commands.execute_dialog = automate
        drive(commands.DownloadCommand().action())
        opened = App.ActiveDocument
        binding = workspace.binding(opened.FileName, client.base_url)
        check(
            "one search window opens default exact newest snapshot",
            binding["entry"]["dataset_id"] == expected[0]["id"],
        )
        check(
            "configured workspace reused without folder prompt",
            not picker_calls and binding["root"] == root,
        )
        check(
            "assembly reconstructs with its published reference pins",
            binding["entry"]["references"]
            == worker(client.get_manifest, expected[0]["id"])["references"],
        )
        saved = workspace.digest(opened.FileName)
        opened.Label = "Local unsaved Open browser fixture"
        docs = set(App.listDocuments())
        drive(commands.DownloadCommand().action())
        check(
            "opening same exact snapshot activates existing dirty document",
            App.ActiveDocument is opened
            and set(App.listDocuments()) == docs
            and cad.document_modified(opened),
        )
        check(
            "reactivation preserves local label and saved bytes",
            opened.Label == "Local unsaved Open browser fixture"
            and workspace.digest(opened.FileName) == saved,
        )
        mode["older"] = True
        drive(commands.DownloadCommand().action())
        historical = App.ActiveDocument
        historical_binding = workspace.binding(historical.FileName, client.base_url)
        check(
            "older snapshot opens separately without replacing dirty latest",
            historical is not opened
            and historical_binding["entry"]["dataset_id"] == expected[-1]["id"]
            and cad.document_modified(opened),
        )
        check(
            "older snapshot keeps its own exact reference manifest",
            historical_binding["entry"]["references"]
            == worker(client.get_manifest, expected[-1]["id"])["references"],
        )
        check(
            "opening does not acquire a checkout",
            worker(client.get_checkout, item["current_revision_id"]) is None,
        )
        check(
            "opening does not create server datasets",
            len(worker(client.list_datasets, item["current_revision_id"])) == len(expected),
        )
        report["status"] = "passed"
    except BaseException as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        commands.execute_dialog, commands._choose_workspace = original_dialog, original_choose
        for name in set(App.listDocuments()) - set(before_docs):
            doc = App.getDocument(name)
            metadata = doc.getObject("ForgePDM_Metadata")
            if metadata:
                tree_observer.revoke_revision(metadata.RevisionId)
            App.closeDocument(name)
        if user:
            key = hashlib.sha256((client.base_url + "\n" + user["id"]).encode()).hexdigest()
            settings._parameters().GetGroup("Workspaces").RemGroup(key)
        session.Session.set_client(*before_session)
        if before_active:
            App.setActiveDocument(before_active)
        executor.shutdown(wait=True)
        report["original_documents_preserved"] = before_docs == {
            d.Name: (d.FileName, cad.document_modified(d)) for d in App.listDocuments().values()
        }
        (case / "open-report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
