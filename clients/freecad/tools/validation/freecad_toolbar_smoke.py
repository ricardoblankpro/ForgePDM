"""Live toolbar regression harness; invoke run(App, Gui) through FreeCAD MCP.

Uses the current logged-in session and read-only Show BOM on the active document.
Additional worker outcomes are injected; a separate invalid-token client tests
HTTP 401 without revoking the user's real login. No CAD/server writes occur.
"""


def run(App, Gui, report_path="/tmp/forgepdm-toolbar-after.json"):
    import importlib
    import json
    from pathlib import Path
    import sys
    import time

    import freecad.forgepdm as package
    from freecad.forgepdm import api, session, tasks, ui
    from freecad.forgepdm.jobs import OperationCancelled, Request

    assert not session.Session.busy
    assert App.ActiveDocument is not None
    original_client = session.Session.require_client()
    original_user = session.Session.user
    document = App.ActiveDocument
    revision_id = document.getObject("ForgePDM_Metadata").RevisionId
    importlib.reload(package)
    importlib.reload(tasks)
    toolbar = next(
        bar
        for bar in Gui.getMainWindow().findChildren(ui.QtWidgets.QToolBar)
        if bar.objectName() == "ForgePDM"
    )
    notifications = []
    originals = {name: getattr(tasks, name) for name in ("information", "error", "warning")}
    report = {
        "freecad": App.Version(),
        "python": sys.version,
        "qt": ui.QtCore.qVersion(),
        "addon_version": package.__version__,
        "checks": [],
        "outcomes": [],
        "scope": "Actual QAction states and read-only toolbar command; injected worker failures/cancel and real HTTP 401",
    }

    def snapshot():
        return {action.objectName(): action.isEnabled() for action in toolbar.actions()}

    def expected():
        return {
            action.objectName(): Gui.Command.get(action.objectName()).isActive()
            for action in toolbar.actions()
        }

    def check(label, value):
        assert value, label
        report["checks"].append(label)

    def wait(job, public=False):
        loop = ui.QtCore.QEventLoop()
        timer = ui.QtCore.QTimer()
        watchdog = ui.QtCore.QTimer()
        modal_ticks, busy_states = [0], []

        def observe():
            if session.Session.busy:
                busy_states.append(snapshot())
            dialog = ui.QtWidgets.QApplication.activeModalWidget()
            if public and dialog and dialog.windowTitle().startswith("ForgePDM BOM"):
                modal_ticks[0] += 1
                if modal_ticks[0] == 20:
                    dialog.accept()
            if job.done and not session.Session.busy and tasks.active_job() is None:
                timer.stop()
                # Command.update queues FreeCAD's activation timer; inspect the
                # real QActions after it runs, without invoking another command.
                ui.QtCore.QTimer.singleShot(450, loop.quit)

        timer.timeout.connect(observe)
        timer.start(20)
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(loop.quit)
        watchdog.start(10000)
        loop.exec()
        timer.stop()
        watchdog.stop()
        assert job.done and not session.Session.busy, "Workflow did not finish"
        return busy_states

    def outcome(label, job, public=False, error_type=None):
        busy_states = wait(job, public)
        check(
            label + ": correct workflow result",
            isinstance(job.error, error_type) if error_type else job.error is None,
        )
        check(label + ": toolbar matches current IsActive state", snapshot() == expected())
        check(
            label + ": commands disabled while busy",
            any(not any(state.values()) for state in busy_states),
        )
        report["outcomes"].append({"name": label, "after": snapshot()})

    def delayed(error=None):
        def request():
            time.sleep(0.4)
            if error:
                raise error

        yield Request("Toolbar regression check", request)

    try:
        for name in originals:
            setattr(
                tasks, name, lambda title, message, kind=name: notifications.append((kind, message))
            )
        # Clear the stale pre-fix state once, before starting the test sequence.
        Gui.Command.update()
        settle = ui.QtCore.QEventLoop()
        ui.QtCore.QTimer.singleShot(350, settle.quit)
        settle.exec()
        for index in range(2):
            action = next(
                action for action in toolbar.actions() if action.objectName() == "ForgePDM_ShowBOM"
            )
            check(
                "Show BOM {}: QAction clickable before invocation".format(index + 1),
                action.isEnabled(),
            )
            action.trigger()
            job = tasks.active_job()
            assert job is not None
            outcome("Show BOM " + str(index + 1), job, public=True)
        outcome(
            "worker error",
            tasks.run(delayed(TimeoutError("Injected toolbar test timeout"))),
            error_type=TimeoutError,
        )
        job = tasks.run(delayed())
        ui.QtCore.QTimer.singleShot(220, job.cancel)
        outcome("cancellation", job, error_type=OperationCancelled)

        def immediate():
            yield from ()

        job = tasks.run(immediate())
        wait(job)
        check(
            "immediate completion restores toolbar", job.error is None and snapshot() == expected()
        )

        invalid_client = api.ForgePDMClient(original_client.base_url, original_client.timeout)
        invalid_client.token = "invalid-toolbar-regression-token"
        session.Session.set_client(invalid_client, original_user)

        def unauthorized():
            yield Request(
                "Testing expired session activation", invalid_client.get_bom, (revision_id,)
            )

        job = tasks.run(unauthorized())
        wait(job)
        check(
            "HTTP 401 invalidates only the test client",
            isinstance(job.error, api.ForgePDMError)
            and job.error.status == 401
            and session.Session.client is None,
        )
        check(
            "expired session toolbar matches login-only activation",
            snapshot() == expected() and snapshot()["ForgePDM_Login"],
        )
        check(
            "expired session keeps protected actions disabled",
            not any(value for key, value in snapshot().items() if key != "ForgePDM_Login"),
        )
        check("active assembly remains unchanged", App.ActiveDocument is document)
        report["status"] = "passed"
    except BaseException as exception:
        report.update({"status": "failed", "error": str(exception)})
        raise
    finally:
        for name, function in originals.items():
            setattr(tasks, name, function)
        session.Session.set_client(original_client, original_user)
        Gui.Command.update()
        settle = ui.QtCore.QEventLoop()
        ui.QtCore.QTimer.singleShot(350, settle.quit)
        settle.exec()
        report["restored_toolbar"] = snapshot()
        report["notifications"] = notifications
        Path(report_path).write_text(json.dumps(report, indent=2) + "\n")
    return report
