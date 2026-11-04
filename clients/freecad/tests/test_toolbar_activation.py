"""Qt completion must refresh FreeCAD's cached command activation state."""

import importlib.util
import sys
import time
from types import ModuleType, SimpleNamespace as NS

import pytest

from freecad.forgepdm.api import ForgePDMError
from freecad.forgepdm.jobs import OperationCancelled, Request
from freecad.forgepdm.session import Session


class Signal:
    def connect(self, callback):
        self.callback = callback

    def emit(self):
        self.callback()


@pytest.fixture
def task_gui(addon_root, monkeypatch):
    timers, dialogs, refreshes, notifications = [], [], [], []

    class Timer:
        def __init__(self, parent):
            self.timeout = Signal()
            self.running = False
            timers.append(self)

        def setInterval(self, interval):
            pass

        def start(self):
            self.running = True

        def stop(self):
            self.running = False

    class Dialog:
        def __init__(self, *args):
            self.canceled = Signal()
            self.closed = self.deleted = False
            dialogs.append(self)

        def ignore(self, *args):
            pass

        setWindowTitle = setMinimumDuration = setAutoClose = setAutoReset = ignore
        setLabelText = setCancelButtonText = setRange = setValue = show = ignore

        def findChild(self, kind):
            return None

        def close(self):
            assert not Session.busy
            self.closed = True

        def deleteLater(self):
            self.deleted = True

    def refresh():
        refreshes.append({"busy": Session.busy, "logged_in": Session.client is not None})

    def notify(*args):
        notifications.append(args)

    gui = ModuleType("FreeCADGui")
    gui.Command = NS(update=refresh)
    app = ModuleType("FreeCAD")
    app.Console = NS(PrintError=lambda text: None)
    ui = ModuleType("freecad.forgepdm.ui")
    ui.QtCore = NS(QTimer=Timer)
    ui.QtWidgets = NS(QProgressDialog=Dialog, QPushButton=object)
    ui.parent_window = lambda: None
    ui.information = ui.warning = ui.error = notify
    for name, module in (("FreeCADGui", gui), ("FreeCAD", app), (ui.__name__, ui)):
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location(
        "freecad.forgepdm._toolbar_tasks", addon_root / "freecad/forgepdm/tasks.py"
    )
    tasks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tasks)
    monkeypatch.setattr(Session, "busy", False)
    monkeypatch.setattr(Session, "client", None)
    monkeypatch.setattr(Session, "user", None)
    return NS(
        tasks=tasks,
        timers=timers,
        dialogs=dialogs,
        refreshes=refreshes,
        notifications=notifications,
    )


@pytest.mark.parametrize("outcome", ["success", "error", "cancel", "expired", "immediate"])
def test_completion_refreshes_activation_and_cleans_up_for_every_outcome(task_gui, outcome):
    class Client:
        token = "test-token"
        expires_at = None

        def read(self):
            if outcome == "error":
                raise TimeoutError("Test timeout")
            if outcome == "expired":
                raise ForgePDMError("Session expired", status=401)
            return 42

    Session.set_client(Client(), {"username": "test"})

    def workflow():
        if outcome != "immediate":
            yield Request("Read", Session.client.read)

    job = task_gui.tasks.run(workflow())
    assert task_gui.refreshes == [{"busy": True, "logged_in": True}]
    if outcome == "cancel":
        assert job.cancel()
    deadline = time.monotonic() + 3
    while Session.busy and time.monotonic() < deadline:
        task_gui.timers[0].timeout.emit()
        time.sleep(0.001)
    assert job.done
    assert not Session.busy
    assert task_gui.tasks.active_job() is None
    assert task_gui.dialogs[0].closed and task_gui.dialogs[0].deleted
    assert not task_gui.timers[0].running
    assert task_gui.refreshes[-1] == {"busy": False, "logged_in": outcome != "expired"}
    if outcome == "cancel":
        assert isinstance(job.error, OperationCancelled)
    if outcome == "expired":
        assert Session.client is None


def test_reporting_failure_still_restores_toolbar_and_disposes_dialog(task_gui, monkeypatch):
    def workflow():
        yield from ()

    def fail_report(job):
        raise RuntimeError("Notification failed")

    monkeypatch.setattr(task_gui.tasks, "_report_result", fail_report)
    task_gui.tasks.run(workflow())
    with pytest.raises(RuntimeError, match="Notification failed"):
        task_gui.timers[0].timeout.emit()
    assert not Session.busy
    assert task_gui.tasks.active_job() is None
    assert task_gui.dialogs[0].deleted
    assert task_gui.refreshes[-1]["busy"] is False


@pytest.mark.parametrize("earlier_change", [False, True])
def test_local_cad_validation_does_not_claim_an_uncertain_upload(task_gui, earlier_change):
    from freecad.forgepdm.fcstd import CADIntegrityError

    def upload():
        raise CADIntegrityError("Missing embedded template")

    def workflow():
        if earlier_change:
            yield Request("Acquire checkout", lambda: {}, mutates=True)
        yield Request("Check In", upload, mutates=True)

    job = task_gui.tasks.run(workflow())
    deadline = time.monotonic() + 3
    while Session.busy and time.monotonic() < deadline:
        task_gui.timers[0].timeout.emit()
        time.sleep(0.001)
    assert isinstance(job.error, CADIntegrityError)
    text = task_gui.notifications[-1][-1]
    assert "local validation" in text and "may have completed" not in text
    assert ("Earlier server changes completed" in text) == earlier_change
