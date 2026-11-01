"""Deferred insertion refresh respects owned lease, session and native edits."""

from datetime import datetime, timedelta, timezone
import sys
from types import ModuleType, SimpleNamespace as NS

import pytest

from freecad.forgepdm import tree_observer as observer
from freecad.forgepdm.session import Session
from freecad.forgepdm.workspace import WorkspaceError


@pytest.fixture
def context(monkeypatch):
    metadata = NS(RevisionId="revision")
    document = NS(
        Name="Assembly",
        FileName="/workspace/working/id/model.FCStd",
        HasPendingTransaction=False,
        Objects=[],
        getObject=lambda name: metadata,
    )
    client = NS(base_url="http://forgepdm.test", token="test", is_expired=lambda: False)
    user = {"id": "user"}
    checkout = {
        "user_id": "user",
        "revision_id": "revision",
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    }
    monkeypatch.setattr(observer, "_leases", {})
    monkeypatch.setattr(Session, "client", client)
    monkeypatch.setattr(Session, "user", user)
    monkeypatch.setattr(Session, "busy", False)
    return NS(document=document, metadata=metadata, client=client, user=user, checkout=checkout)


def test_grants_are_bound_to_owned_lease_document_revision_server_and_session(context):
    case = context
    assert not observer.can_edit(case.document)
    observer.allow_edit(case.document, case.checkout, case.client, case.user)
    assert observer.can_edit(case.document)
    case.document.FileName = "/other/model.FCStd"
    assert not observer.can_edit(case.document)
    case.document.FileName = "/workspace/working/id/model.FCStd"
    case.metadata.RevisionId = "another-revision"
    assert not observer.can_edit(case.document)
    case.metadata.RevisionId = "revision"
    Session.user = {"id": "someone-else"}
    assert not observer.can_edit(case.document)


@pytest.mark.parametrize(
    "change",
    [
        {"user_id": "other"},
        {"revision_id": "other"},
        {"expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()},
    ],
)
def test_invalid_lease_cannot_enable_automatic_label_writes(context, change):
    with pytest.raises(WorkspaceError):
        observer.allow_edit(
            context.document, dict(context.checkout, **change), context.client, context.user
        )
    assert not observer.can_edit(context.document)


def test_checkin_revokes_cached_label_editing_permission(context):
    observer.allow_edit(context.document, context.checkout, context.client, context.user)
    observer.revoke_revision(context.metadata.RevisionId)
    assert not observer.can_edit(context.document)


def test_observer_defers_for_jobs_and_native_transactions_and_skips_after_logout(
    context, monkeypatch
):
    case = context

    class Timer:
        def __init__(self):
            self.timeout = NS(connect=lambda callback: None)
            self.starts = 0

        def setSingleShot(self, value):
            pass

        def setInterval(self, value):
            pass

        def start(self):
            self.starts += 1

    app = ModuleType("FreeCAD")
    app.listDocuments = lambda: {case.document.Name: case.document}
    app.Console = NS(PrintWarning=lambda text: pytest.fail(text))
    ui = ModuleType("freecad.forgepdm.ui")
    ui.QtCore = NS(QTimer=Timer)
    ui.QtWidgets = NS(QApplication=NS(activeModalWidget=lambda: None))
    monkeypatch.setitem(sys.modules, "FreeCAD", app)
    monkeypatch.setitem(sys.modules, ui.__name__, ui)
    refreshed = []
    monkeypatch.setattr(
        observer.tree_labels, "refresh", lambda document: refreshed.append(document)
    )
    observer.allow_edit(case.document, case.checkout, case.client, case.user)
    instance = observer.TreeObserver()
    instance.slotCreatedObject(NS(TypeId="App::Link", Document=case.document))
    assert instance.pending == {case.document.Name}
    instance.slotChangedObject(NS(Name="Link", Document=case.document), "LinkedObject")
    Session.busy = True
    instance.flush()
    assert not refreshed
    Session.busy = False
    case.document.HasPendingTransaction = True
    instance.flush()
    assert not refreshed
    case.document.HasPendingTransaction = False
    instance.flush()
    assert refreshed == [case.document]
    instance.queue(case.document)
    Session.client = None
    instance.flush()
    assert refreshed == [case.document]
