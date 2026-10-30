"""Qt adapter. Timer polling resumes workflows exclusively on the GUI thread."""

from .api import ForgePDMError
from .jobs import OperationCancelled, WorkflowJob
from .session import Session
from .ui import QtCore, QtWidgets, error, information, parent_window, warning


_active = None


def active_job():
    return _active


def run(workflow):
    global _active
    if Session.busy:
        workflow.close()
        warning("ForgePDM", "Wait for the current ForgePDM operation to finish.")
        return
    job = WorkflowJob(workflow)
    dialog = QtWidgets.QProgressDialog("Connecting…", "Cancel", 0, 0, parent_window())
    dialog.setWindowTitle("ForgePDM")
    dialog.setMinimumDuration(250)
    dialog.setAutoClose(False)
    dialog.setAutoReset(False)
    cancel_button = dialog.findChild(QtWidgets.QPushButton)
    timer = QtCore.QTimer(dialog)
    timer.setInterval(30)

    def cancel():
        if job.cancel():
            dialog.setLabelText("Canceling… waiting for the current request to finish.")

    def poll():
        global _active
        job.poll()
        if job.done:
            timer.stop()
            dialog.close()
            Session.busy = False
            _active = None
            if isinstance(job.error, OperationCancelled):
                text = "Operation canceled."
                if job.may_have_changed_server:
                    text += (
                        " A server change may have completed. Check the revision before retrying."
                    )
                information("ForgePDM", text)
            elif job.error is not None:
                client = job.request.client if job.request else None
                if isinstance(job.error, ForgePDMError) and job.error.status == 401:
                    if client is Session.client:
                        Session.invalidate()
                        text = "Your session expired or was revoked. Log in again to continue."
                    elif getattr(job.request.function, "__name__", "") == "login":
                        text = "Login failed. Check your username and password."
                    else:
                        text = "The server session is no longer valid. Log in again to continue."
                else:
                    text = str(job.error)
                rejected = getattr(job.error, "status", None) in (400, 401, 403, 404, 409, 422)
                if job.completed_mutations or (job.may_have_changed_server and not rejected):
                    text += "\nA server change may have completed; do not retry blindly."
                import FreeCAD

                label = job.request.label if job.request else "Preparing operation"
                code = getattr(job.error, "code", "workflow_failed")
                FreeCAD.Console.PrintError("ForgePDM [{}] {}: {}\n".format(code, label, text))
                error("ForgePDM", text)
            dialog.deleteLater()
            return
        if job.request is not None and not job.context.cancelled.is_set():
            dialog.setLabelText(job.request.label)
            dialog.setCancelButtonText("Cancel")
            if cancel_button is not None:
                cancel_button.setEnabled(job.request.cancellable)
            progress = job.context.latest_progress()
            if progress and progress[1] > 0:
                dialog.setRange(0, 100)
                dialog.setValue(min(99, int(100 * progress[0] / progress[1])))
            else:
                dialog.setRange(0, 0)

    dialog.canceled.connect(cancel)
    timer.timeout.connect(poll)
    _active = job
    Session.busy = True
    job.start()
    timer.start()
    if not job.done:
        dialog.show()
    return job
