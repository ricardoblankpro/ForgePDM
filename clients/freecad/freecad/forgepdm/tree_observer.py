"""Deferred local tree updates under an explicitly verified owned checkout."""

from datetime import datetime, timezone

from . import tree_labels
from .session import Session


_observer = None
_leases = {}


def revoke_revision(revision_id):
    for name, lease in list(_leases.items()):
        if lease[2] == revision_id:
            _leases.pop(name, None)


def allow_edit(document, checkout, client, user):
    if not checkout or checkout["user_id"] != (user or {}).get("id"):
        raise tree_labels.WorkspaceError(
            "Acquire your own assembly checkout before refreshing tree labels"
        )
    expires = datetime.fromisoformat(checkout["expires_at"])
    if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
        raise tree_labels.WorkspaceError(
            "The checkout expired; acquire it again before refreshing tree labels"
        )
    metadata = document.getObject("ForgePDM_Metadata")
    if checkout["revision_id"] != metadata.RevisionId:
        raise tree_labels.WorkspaceError(
            "The document revision changed while checking its checkout"
        )
    _leases[document.Name] = (
        document,
        document.FileName,
        metadata.RevisionId,
        client.base_url,
        checkout["user_id"],
        expires,
    )


def can_edit(document):
    lease = _leases.get(document.Name)
    client, user = Session.client, Session.user or {}
    metadata = document.getObject("ForgePDM_Metadata")
    return bool(
        lease
        and lease[0] is document
        and lease[1] == document.FileName
        and metadata is not None
        and lease[2] == metadata.RevisionId
        and client is not None
        and client.token
        and lease[3] == client.base_url
        and lease[4] == user.get("id")
        and lease[5] > datetime.now(timezone.utc)
        and not client.is_expired()
    )


class TreeObserver:
    def __init__(self):
        from .ui import QtCore

        self.pending = set()
        self.timer = QtCore.QTimer()
        self.timer.setSingleShot(True)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.flush)

    def queue(self, document):
        if can_edit(document):
            self.pending.add(document.Name)
            self.timer.start()

    def slotCreatedObject(self, obj):
        if obj.TypeId == "App::Link":
            self.queue(obj.Document)

    def slotChangedObject(self, obj, property_name):
        if property_name not in (
            "LinkedObject",
            "Group",
            "ItemNumber",
            "RevisionLabel",
            "RevisionId",
        ):
            return
        import FreeCAD as App

        document = obj.Document
        self.queue(document)
        if obj.Name == "ForgePDM_Metadata":
            for parent in App.listDocuments().values():
                if can_edit(parent) and any(
                    link.TypeId == "App::Link"
                    and getattr(getattr(link, "LinkedObject", None), "Document", None) is document
                    for link in parent.Objects
                ):
                    self.queue(parent)

    def slotDeletedDocument(self, document):
        _leases.pop(document.Name, None)
        self.pending.discard(document.Name)

    def flush(self):
        import FreeCAD as App
        from .ui import QtWidgets

        if Session.busy or QtWidgets.QApplication.activeModalWidget() is not None:
            if self.pending:
                self.timer.start()
            return
        pending, self.pending = self.pending, set()
        for name in pending:
            document = App.listDocuments().get(name)
            if document is None or not can_edit(document):
                continue
            if getattr(document, "HasPendingTransaction", False):
                self.pending.add(name)
                continue
            try:
                tree_labels.refresh(document)
            except Exception as error:
                App.Console.PrintWarning("ForgePDM tree labels ({}): {}\n".format(name, error))
        if self.pending:
            self.timer.start()


def install():
    global _observer
    if _observer is None:
        import FreeCAD as App

        _observer = TreeObserver()
        App.addDocumentObserver(_observer)


def uninstall():
    global _observer
    if _observer is not None:
        import FreeCAD as App

        _observer.timer.stop()
        App.removeDocumentObserver(_observer)
        _observer = None
    _leases.clear()
