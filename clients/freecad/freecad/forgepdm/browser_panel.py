"""One modeless dock per authenticated session; no startup network work."""

from .open_ui import OpenDialog
from .session import Session
from .ui import QtCore, QtWidgets

_dock = None


def current_session(client, actor):
    return (
        Session.client is client and (Session.user or {}).get("id") == actor and bool(client.token)
    )


class BrowserDock(QtWidgets.QDockWidget):
    def __init__(self, parent, client, actor, root, choose_workspace, open_selection):
        super().__init__("ForgePDM Browser", parent)
        self.setObjectName("ForgePDMBrowserDock")
        self.client, self.actor = client, actor
        self.destroyed.connect(lambda *_: forget(self))
        self.setMinimumWidth(420)

        def opening(selection):
            if not current_session(client, actor):
                raise RuntimeError("Log in again to open this item.")
            if Session.busy:
                raise RuntimeError("Wait for the current ForgePDM operation to finish.")
            return open_selection(selection)

        self.view = OpenDialog(
            self,
            client,
            root,
            choose_workspace,
            actor_id=actor,
            on_open=opening,
            session_valid=lambda: current_session(client, actor),
        )
        self.setWidget(self.view)
        self.view.finished.connect(self.deleteLater)
        self.visibilityChanged.connect(self.visibility)
        parent.addDockWidget(QtCore.Qt.LeftDockWidgetArea, self)
        parent.restoreDockWidget(self)

    def visibility(self, visible):
        if visible and not self.view.finishing:
            self.view.timer.start(30)
            if self.view.open_job is None:
                self.view.search()
            self.view.query.setFocus()
        elif not visible and not self.view.finishing:
            self.view.pause()

    def dispose(self):
        self.hide()
        self.view.pause(clear=True)
        self.view.finish(0)

    def closeEvent(self, event):
        event.ignore()
        self.hide()


def forget(dock):
    global _dock
    if _dock is dock:
        _dock = None


def show_browser(parent, client, actor, root, choose_workspace, open_selection):
    global _dock
    if _dock is not None and not current_session(_dock.client, _dock.actor):
        previous, _dock = _dock, None
        previous.dispose()
    if _dock is None:
        _dock = BrowserDock(parent, client, actor, root, choose_workspace, open_selection)
    else:
        _dock.view.root = root
        _dock.view.workspace.setText(root or "Choose a workspace once")
    _dock.show()
    _dock.raise_()
    _dock.view.query.setFocus()
    _dock.view.query.selectAll()
    return _dock


def session_changed():
    global _dock
    if _dock is not None and not current_session(_dock.client, _dock.actor):
        previous, _dock = _dock, None
        previous.dispose()
