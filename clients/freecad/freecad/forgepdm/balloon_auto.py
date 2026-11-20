"""Deferred adoption after native placement and arrow movements, never on restore."""

from . import balloon_geometry as geometry, drawing_balloons as links, drawing_bom
from .session import Session

_observer = None


def workflow(balloon):
    from . import commands, workspace
    from .jobs import Request
    from .ui import ask_choice
    from datetime import datetime, timezone

    document = balloon.Document
    metadata = commands._require_metadata(document)
    client = Session.require_client()
    actor = (Session.user or {}).get("id")
    path, name, rid = document.FileName, document.Name, metadata.RevisionId
    workspace.binding(path, client.base_url, require_uploaded=False)
    if workspace.working_path(path, client.base_url) is None:
        raise ValueError("Prepare a managed Working copy before automatic balloon linking")
    before = geometry.signature(balloon), links.review_state(balloon)
    yield from commands._editable(client, metadata)
    yield Request("Checking balloon edit permission…", client.bom_snapshot, (rid,))
    lease = yield Request("Checking balloon checkout…", client.get_checkout, (rid,))
    if (
        not lease
        or lease["user_id"] != actor
        or datetime.fromisoformat(lease["expires_at"]) <= datetime.now(timezone.utc)
    ):
        raise ValueError("Acquire your own live checkout before automatic balloon linking")
    commands._guard_document(name, rid)
    if (
        Session.client is not client
        or (Session.user or {}).get("id") != actor
        or document.FileName != path
        or before != (geometry.signature(balloon), links.review_state(balloon))
    ):
        raise ValueError("Document, geometry or session changed; retry Link BOM Balloon")
    page = next(
        (p for p in document.Objects if p.TypeId == "TechDraw::DrawPage" and balloon in p.Views),
        None,
    )
    if page is None:
        raise ValueError("The balloon must belong to a TechDraw page")
    tables = []
    for obj in page.Views:
        if hasattr(obj, "PDMTableData"):
            data = drawing_bom.read_table(obj)
            if (
                data["report"].get("revision_id") == rid
                and data["report"].get("view", "direct") == "direct"
            ):
                tables.append(obj)
    cancelled = False
    table = getattr(balloon, "PDMBOMTable", None)
    if table not in tables:
        if not tables:
            links.unresolved(balloon, "Insert a Direct Drawing BOM table for this assembly first")
            raise ValueError("Insert a Direct Drawing BOM table for this assembly first")
        index = (
            0
            if len(tables) == 1
            else choose("Choose the target BOM table", [t.Label for t in tables], ask_choice)
        )
        if index is None:
            cancelled = True
            index = 0
        table = tables[index]
    table_before = table.PDMTableData
    failure = "Target table selection cancelled" if cancelled else None
    try:
        if failure:
            raise ValueError(failure)
        data = drawing_bom.read_table(table)
        options = geometry.candidates(balloon, data)
        if not options:
            raise ValueError(
                "The touched component is absent from the frozen BOM; update Drawing BOM"
            )
        index = (
            0
            if len(options) == 1
            else choose(
                "Overlapping geometry or split BOM entries: choose the intended component",
                [
                    f"{line['item_number']} Rev {line['revision_label']} — Position {line['position']}"
                    f" — {line.get('description') or line.get('item_name') or 'No description'}"
                    for _, line in options
                ],
                ask_choice,
                options,
            )
        )
        if index is None:
            raise ValueError("Component selection cancelled")
        obj, line = options[index]
        attachment = dict(geometry=geometry.evidence(balloon), component=obj.Name)
    except ValueError as error:
        failure = str(error)

    yield from commands._editable(client, metadata)
    yield Request("Revalidating balloon permission…", client.bom_snapshot, (rid,))
    current = yield Request("Revalidating balloon checkout…", client.get_checkout, (rid,))
    commands._guard_document(name, rid)
    import FreeCADGui as Gui

    if (
        Session.client is not client
        or (Session.user or {}).get("id") != actor
        or document.FileName != path
        or before != (geometry.signature(balloon), links.review_state(balloon))
        or table.PDMTableData != table_before
        or table not in page.Views
        or balloon not in page.Views
        or Gui.getDocument(name).getInEdit()
        or workspace.working_path(path, client.base_url) is None
        or not current
        or current["user_id"] != actor
        or (current["id"], current["version"]) != (lease["id"], lease["version"])
        or datetime.fromisoformat(current["expires_at"]) <= datetime.now(timezone.utc)
    ):
        raise ValueError("Drawing, session or checkout changed; retry Link BOM Balloon")
    if failure:
        links.unresolved(balloon, failure)
        raise ValueError(failure)
    links.bind(document, page, balloon, table, drawing_bom.row_key(line), attachment)


def choose(prompt, labels, ask, options=None):
    import FreeCADGui as Gui

    previous = [(s.Object, list(s.SubElementNames)) for s in Gui.Selection.getSelectionEx()]
    try:
        if options:
            Gui.Selection.clearSelection()
            for obj, _ in options:
                Gui.Selection.addSelection(obj)
        choices = [f"{i + 1}. {label}" for i, label in enumerate(labels)]
        selected = ask("Automatic BOM Balloon", prompt, choices)
        return None if selected is None else choices.index(selected)
    finally:
        Gui.Selection.clearSelection()
        for obj, subs in previous:
            for sub in subs or [""]:
                Gui.Selection.addSelection(obj, sub)


class Observer:
    def __init__(self):
        from .ui import QtCore

        self.pending = set()
        self.suspended = False
        self.timer = QtCore.QTimer()
        self.timer.setSingleShot(True)
        self.timer.setInterval(350)
        self.timer.timeout.connect(self.flush)

    def queue(self, obj):
        if (
            self.suspended
            or getattr(obj.Document, "Restoring", False)
            or obj.TypeId != "TechDraw::DrawViewBalloon"
        ):
            return
        if obj.Document.getObject("ForgePDM_Metadata") is not None:
            self.pending.add((obj.Document.Name, obj.Name))
            self.timer.start()

    def slotCreatedObject(self, obj):
        self.queue(obj)

    def slotChangedObject(self, obj, prop):
        if prop in ("OriginX", "OriginY", "SourceView"):
            self.queue(obj)

    def slotUndoDocument(self, document):
        self.pending = {key for key in self.pending if key[0] != document.Name}

    slotRedoDocument = slotUndoDocument
    slotAbortTransaction = slotUndoDocument

    def slotDeletedDocument(self, document):
        self.slotUndoDocument(document)

    def flush(self):
        import FreeCAD as App
        import FreeCADGui as Gui
        from .ui import QtCore, QtWidgets
        from .tasks import run

        if (
            Session.busy
            or QtCore.QThreadPool.globalInstance().activeThreadCount()
            or QtWidgets.QApplication.activeModalWidget()
            or QtWidgets.QApplication.mouseButtons()
        ):
            self.timer.start()
            return
        for key in list(self.pending):
            doc = App.listDocuments().get(key[0])
            if doc is None or doc.getObject(key[1]) is None:
                self.pending.discard(key)
                continue
            if doc.HasPendingTransaction or Gui.getDocument(doc.Name).getInEdit():
                self.timer.start()
                return
            self.pending.discard(key)
            if Session.client is None:
                App.Console.PrintWarning(
                    "ForgePDM: log in and use Link BOM Balloon to resolve the moved arrow.\n"
                )
                continue
            run(workflow(doc.getObject(key[1])))
            if self.pending:
                self.timer.start()
            return


def install():
    global _observer
    if _observer is None:
        import FreeCAD as App

        _observer = Observer()
        App.addDocumentObserver(_observer)
