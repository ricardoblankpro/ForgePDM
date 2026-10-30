"""Live FreeCAD MCP harness. Supply PHASE2_CASE with isolated server credentials.

This file is intentionally outside pytest discovery: it requires real FreeCAD.
Never point the configuration at a production server.
"""


def run(case_directory):
    from datetime import datetime, timedelta, timezone
    import importlib
    import json
    from pathlib import Path
    import sys
    from threading import get_ident
    import time
    import traceback

    import FreeCAD as App
    import FreeCADGui as Gui
    from freecad.forgepdm import session

    case = Path(case_directory)
    configuration = json.loads((case / "connection.json").read_text())
    original_client, original_user = session.Session.client, session.Session.user
    original_documents = set(App.listDocuments())
    original_active = App.ActiveDocument.Name if App.ActiveDocument else None
    original_workbench = Gui.activeWorkbench().name()
    # Reload only for local testing of an already-running installation. A clean
    # startup uses init_gui normally and needs no runtime reload mechanism.
    from freecad.forgepdm import api, jobs, settings, ui

    for module in (api, jobs, session, settings, ui):
        importlib.reload(module)
    from freecad.forgepdm import tasks, commands

    importlib.reload(tasks)
    importlib.reload(commands)
    if original_client is not None:
        refreshed = api.ForgePDMClient(original_client.base_url, original_client.timeout)
        refreshed.token = original_client.token
        refreshed.expires_at = getattr(original_client, "expires_at", None)
        original_client = refreshed
    preferences = settings.load()
    main_thread = get_ident()
    workers, gui_calls, messages, failures = [], [], [], []
    report = {
        "freecad": App.Version(),
        "python": sys.version,
        "qt": ui.QtCore.qVersion(),
        "checks": [],
        "scope": "Real FreeCAD and isolated backend; dialog choices automated",
    }
    original_methods = {
        name: getattr(commands, name)
        for name in (
            "ask_text",
            "ask_choice",
            "information",
            "warning",
            "QtWidgets",
            "execute_dialog",
            "_save_document",
            "_set_metadata",
            "ForgePDMClient",
        )
    }
    original_feedback = {name: getattr(tasks, name) for name in ("error", "information", "warning")}
    original_login_form = ui.login_form
    names = (
        "Login",
        "Logout",
        "Upload",
        "Checkout",
        "CheckIn",
        "Release",
        "NewRevision",
        "Download",
        "ShowBOM",
    )
    classes = (
        commands.LoginCommand,
        commands.LogoutCommand,
        commands.UploadCommand,
        commands.CheckoutCommand,
        commands.CheckInCommand,
        commands.ReleaseCommand,
        commands.NewRevisionCommand,
        commands.DownloadCommand,
        commands.ShowBOMCommand,
    )
    # FreeCAD does not replace callbacks for already-registered names. For
    # this in-process test only, rebind the retained Python instances. Normal
    # installations use a restart and do not rely on garbage-collector access.
    import gc

    command_classes = {command.__name__: command for command in classes}
    rebound = 0
    for instance in gc.get_objects():
        previous = type(instance)
        if previous.__module__ == commands.__name__ and previous.__name__ in command_classes:
            instance.__class__ = command_classes[previous.__name__]
            rebound += 1
    report["callbacks_rebound_for_live_test"] = rebound
    for name, command in zip(names, classes):
        if "ForgePDM_" + name not in Gui.listCommands():
            Gui.addCommand("ForgePDM_" + name, command())

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        report["checks"].append(name)

    class TrackedClient(api.ForgePDMClient):
        def _json_request(self, method, path, *args, **kwargs):
            workers.append(get_ident())
            if path.startswith("/api/v1/projects"):
                time.sleep(0.3)
            return super()._json_request(method, path, *args, **kwargs)

        def upload_file(self, *args, **kwargs):
            workers.append(get_ident())
            return super().upload_file(*args, **kwargs)

        def download_file(self, *args, **kwargs):
            workers.append(get_ident())
            return super().download_file(*args, **kwargs)

    def gui_only(function):
        def wrapped(*args, **kwargs):
            gui_calls.append(get_ident())
            assert get_ident() == main_thread
            return function(*args, **kwargs)

        return wrapped

    def wait(job):
        loop = ui.QtCore.QEventLoop()
        heartbeat = ui.QtCore.QTimer()
        watchdog = ui.QtCore.QTimer()
        count = [0]

        def tick():
            count[0] += 1
            if tasks.active_job() is None:
                loop.quit()

        heartbeat.timeout.connect(tick)
        heartbeat.start(10)
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(loop.quit)
        watchdog.start(15000)
        loop.exec() if hasattr(loop, "exec") else loop.exec_()
        heartbeat.stop()
        watchdog.stop()
        assert job.done, "Background job did not finish"
        return count[0]

    def invoke(name, expect_error=False):
        Gui.runCommand("ForgePDM_" + name, 0)
        job = tasks.active_job()
        assert job is not None
        ticks = wait(job)
        if not expect_error:
            check(name + " completed", job.error is None)
        return job, ticks

    item_number = [""]
    project_choices = []

    def ask_text(title, label, default="", password=False):
        assert get_ident() == main_thread
        if title == "Find ForgePDM Item":
            return item_number[0]
        if title in ("ForgePDM Check In", "ForgePDM New Revision"):
            return "Phase 2 MCP test"
        raise AssertionError("Unexpected text prompt: " + title)

    def ask_choice(title, prompt, choices, default=None):
        assert get_ident() == main_thread
        if title == "New ForgePDM Item":
            return "part"
        if title == "Projects":
            project_choices.extend(choices)
            return choices[0]
        if title == "Revisions":
            return next(choice for choice in choices if choice.startswith("A —"))
        return choices[0]

    class FileDialogs:
        @staticmethod
        def getExistingDirectory(*args):
            path = case / "downloads"
            path.mkdir(exist_ok=True)
            return str(path)

    class WidgetsProxy:
        def __getattr__(self, name):
            return FileDialogs if name == "QFileDialog" else getattr(ui.QtWidgets, name)

    def auto_bom(dialog):
        assert get_ident() == main_thread
        ui.QtCore.QTimer.singleShot(0, dialog.accept)
        return ui.execute_dialog(dialog)

    def login():
        # Exercise the actual login form, automatically fill it on its GUI thread.
        def fill():
            for dialog in ui.QtWidgets.QApplication.topLevelWidgets():
                if (
                    isinstance(dialog, ui.QtWidgets.QDialog)
                    and dialog.windowTitle() == "Connect to ForgePDM"
                ):
                    fields = dialog.findChildren(ui.QtWidgets.QLineEdit)
                    for field, value in zip(
                        fields,
                        (
                            configuration["base_url"],
                            configuration["username"],
                            configuration["password"],
                        ),
                    ):
                        field.setText(value)
                    dialog.findChild(ui.QtWidgets.QSpinBox).setValue(2)
                    dialog.accept()
                    return

        ui.QtCore.QTimer.singleShot(0, fill)
        return invoke("Login")

    try:
        session.Session.clear()  # Detach without revoking the user's session.
        commands.ForgePDMClient = TrackedClient
        commands.ask_text, commands.ask_choice = ask_text, ask_choice
        commands.QtWidgets = WidgetsProxy()
        commands.execute_dialog = auto_bom
        commands._save_document = gui_only(original_methods["_save_document"])
        commands._set_metadata = gui_only(original_methods["_set_metadata"])
        commands.information = lambda title, text: messages.append(text)
        commands.warning = lambda title, text: messages.append(text)
        tasks.error = lambda title, text: failures.append(text)
        tasks.information = lambda title, text: messages.append(text)
        tasks.warning = lambda title, text: messages.append(text)
        check(
            "Nine existing command IDs retained",
            {"ForgePDM_" + name for name in names} <= set(Gui.listCommands()),
        )
        check("Backend package absent from FreeCAD", "forgepdm" not in sys.modules)
        login()
        check(
            "Non-secret connection settings saved",
            settings.load()["url"] == configuration["base_url"],
        )
        keys = {entry[1].lower() for entry in settings._parameters().GetContents()}
        check(
            "No credentials or tokens persisted",
            not keys.intersection({"password", "token", "access_token"}),
        )
        document = App.newDocument("ForgePDMPhase2Smoke")
        box = document.addObject("Part::Box", "SmokeBox")
        box.Length, box.Width, box.Height = 10, 20, 30
        document.recompute()
        document.saveAs(str(case / "working.FCStd"))
        _job, ticks = invoke("Upload")
        check("GUI heartbeat continues during delayed catalog HTTP", ticks >= 10)
        check(
            "Project picker shows only authorized human-readable project",
            project_choices == ["PRJ-SMOKE — MCP Smoke"],
        )
        metadata = commands._require_metadata(document)
        item_number[0] = metadata.ItemNumber
        revision_a = metadata.RevisionId
        invoke("Checkout")
        invoke("CheckIn")
        invoke("Release")
        invoke("NewRevision")
        box.Length = 15
        document.recompute()
        invoke("CheckIn")
        invoke("ShowBOM")
        invoke("Download")
        historical = App.ActiveDocument
        check(
            "Selected historical revision A retrieved rather than current B",
            commands._require_metadata(historical).RevisionId == revision_a,
        )
        check(
            "Historical CAD geometry preserved",
            abs(historical.getObject("SmokeBox").Length.Value - 10) < 1e-8,
        )
        check(
            "HTTP and file transfers run outside GUI thread",
            bool(workers) and all(thread != main_thread for thread in workers),
        )
        check(
            "Document saves and metadata changes stay on GUI thread",
            bool(gui_calls) and all(thread == main_thread for thread in gui_calls),
        )
        invoke("Logout")
        check("Logout clears session", session.Session.client is None)
        login()
        App.setActiveDocument(document.Name)
        session.Session.client.token = "invalid-test-token"
        job, _ticks = invoke("Checkout", expect_error=True)
        check(
            "HTTP 401 clears session and gives login recovery",
            isinstance(job.error, api.ForgePDMError)
            and job.error.status == 401
            and session.Session.client is None
            and "Log in again" in failures[-1],
        )
        login()
        active_client = session.Session.client
        active_client.expires_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        count = len(workers)
        job, _ticks = invoke("Checkout", expect_error=True)
        check(
            "Local expiry prevents network request and clears token",
            job.error is not None
            and len(workers) == count
            and session.Session.client is None
            and active_client.token is None,
        )

        slow_client = api.ForgePDMClient(configuration["slow_url"], timeout=1)
        slow_client.token = "isolated-test-token"

        def timeout_workflow():
            yield jobs.Request("Testing timeout…", slow_client.search_items)

        job = tasks.run(timeout_workflow())
        ticks = wait(job)
        check(
            "Network timeout reported while GUI stays responsive",
            isinstance(job.error, api.ForgePDMError)
            and job.error.code == "connection_failed"
            and ticks >= 20,
        )
        destination = case / "canceled.FCStd"

        def cancel_workflow():
            yield jobs.Request(
                "Testing transfer cancellation…",
                slow_client.download_file,
                ("slow", str(destination)),
            )

        job = tasks.run(cancel_workflow())
        ui.QtCore.QTimer.singleShot(180, job.cancel)
        wait(job)
        check(
            "Live HTTP download cancellation stops continuation",
            isinstance(job.error, jobs.OperationCancelled),
        )
        check(
            "Canceled transfer leaves no destination or partial files",
            not destination.exists() and not list(case.glob(".forgepdm-*.part")),
        )
        check("Expected failures are reported, not suppressed", len(failures) == 3)
        report["result"] = "passed"
    except BaseException:
        report["result"] = "failed"
        report["exception"] = traceback.format_exc()
    finally:
        for name, method in original_methods.items():
            setattr(commands, name, method)
        for name, method in original_feedback.items():
            setattr(tasks, name, method)
        ui.login_form = original_login_form
        test_client = session.Session.client
        if test_client is not None:
            # Do not run network cleanup on the GUI thread. The disposable
            # backend is stopped by the external harness immediately afterward.
            test_client.token = None
        session.Session.client, session.Session.user = original_client, original_user
        settings.save(preferences["url"], preferences["username"], preferences["timeout"])
        for name in list(App.listDocuments()):
            if name not in original_documents:
                App.closeDocument(name)
        if original_active and original_active in App.listDocuments():
            App.setActiveDocument(original_active)
        Gui.activateWorkbench(original_workbench)
        report["original_documents_preserved"] = set(App.listDocuments()) == original_documents
        report["original_identity_restored"] = session.Session.user is original_user
        report["worker_thread_count"] = len(set(workers))
        report["expected_error_count"] = len(failures)
        (case / "freecad-result.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))


if "PHASE2_CASE" in globals():
    run(globals()["PHASE2_CASE"])
