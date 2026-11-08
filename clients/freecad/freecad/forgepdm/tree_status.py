"""Ephemeral native-tree status column. All CAD/Qt access stays on the GUI thread."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html import escape
from time import monotonic
from uuid import UUID

import FreeCAD as App
import FreeCADGui as Gui

from . import cad, pdm_status, descriptions
from .api import ForgePDMError
from .jobs import Context, Request
from .session import Session
from .ui import QtCore, QtGui, QtWidgets

COLUMN = 3
DESCRIPTION_COLUMN = 4
MARKER = "ForgePDM-status-v1"
_controller = None


def linked_object(obj):
    seen = set()
    while obj is not None and obj.TypeId in ("App::Link", "Assembly::AssemblyLink"):
        key = (obj.Document.Name, obj.Name)
        if key in seen or getattr(obj, "ElementCount", 0):
            return None
        seen.add(key)
        obj = obj.LinkedObject
        if isinstance(obj, tuple):
            return None
    return obj


def collect(client):
    """Capture identities only; workers must never receive FreeCAD objects."""
    targets, rows = {}, {}

    def target(document):
        metadata = document.getObject("ForgePDM_Metadata")
        if metadata is None:
            return None
        try:
            item_id, revision_id = str(UUID(metadata.ItemId)), str(UUID(metadata.RevisionId))
        except (ValueError, AttributeError, TypeError):
            return None
        key = (document.Name, id(document), document.FileName, item_id, revision_id)
        if key not in targets:
            description = descriptions.local(document)
            targets[key] = dict(
                description=description["description"] if description else None,
                description_token=description.get("expected_token") if description else None,
                key=key,
                path=document.FileName,
                item_id=item_id,
                revision_id=revision_id,
                dirty=cad.document_modified(document),
                foreign=getattr(metadata, "ServerUrl", client.base_url).rstrip("/")
                != client.base_url,
            )
        return key

    containers = {"PartDesign::Body", "App::Part", "Assembly::AssemblyObject"}
    for document in App.listDocuments().values():
        root = target(document)
        if root:
            rows[(document.Name, "")] = root
        for obj in document.Objects:
            if obj.TypeId in ("App::Link", "Assembly::AssemblyLink"):
                source = linked_object(obj)
                key = target(source.Document) if source is not None else None
            elif root and (
                obj.TypeId in containers
                or (
                    obj.isDerivedFrom("Part::Feature")
                    and not any(parent.TypeId in containers for parent in obj.InList)
                )
            ):
                key = root
            else:
                key = None
            if key:
                rows[(document.Name, obj.Name)] = key
    return targets, rows


def document_for_item(item, documents):
    """Never guess between identical open copies with the same display label."""
    names = [item.child(i).text(2) for i in range(item.childCount()) if item.child(i).text(2)]
    candidates = [
        doc
        for doc in documents
        if doc.Label == item.text(0) and all(doc.getObject(name) is not None for name in names)
    ]
    return candidates[0] if len(candidates) == 1 else None


def object_for_item(item, document, parent):
    name = item.text(2)
    if parent is not None and parent.TypeId in ("App::Link", "Assembly::AssemblyLink"):
        generated = [obj for obj in getattr(parent, "Group", ()) if obj.Name == name]
        if len(generated) == 1:
            return generated[0]
        source = linked_object(parent)
        return source.Document.getObject(name) if source is not None else None
    return document.getObject(name)


class StatusDelegate(QtWidgets.QStyledItemDelegate):
    def createEditor(self, *args):
        return None

    def paint(self, painter, option, index):
        badges = index.data(QtCore.Qt.UserRole) or []
        if not badges:
            return super().paint(painter, option, index)
        styled = QtWidgets.QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        styled.text, styled.icon = "", QtGui.QIcon()
        style = styled.widget.style() if styled.widget else QtWidgets.QApplication.style()
        style.drawControl(QtWidgets.QStyle.CE_ItemViewItem, styled, painter, styled.widget)
        painter.save()
        painter.setClipRect(option.rect)
        x, y = option.rect.x() + 4, option.rect.center().y()
        metrics = option.fontMetrics
        text_color = option.palette.color(
            QtGui.QPalette.HighlightedText
            if option.state & QtWidgets.QStyle.State_Selected
            else QtGui.QPalette.Text
        )
        for badge in badges:
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor(badge["color"]))
            painter.drawEllipse(x, y - 4, 8, 8)
            x += 12
        painter.setPen(text_color)
        text = metrics.elidedText(
            index.data(QtCore.Qt.DisplayRole) or "",
            QtCore.Qt.ElideRight,
            max(0, option.rect.right() - x - 3),
        )
        painter.drawText(x, y + (metrics.ascent() - metrics.descent()) // 2, text)
        painter.restore()


class Column:
    def __init__(self):
        self.trees = {}
        self.icons = {}

    def icon(self, badges):
        colors = tuple(b["color"] for b in badges)
        if colors not in self.icons:
            pixmap = QtGui.QPixmap(12 * len(colors), 14)
            pixmap.fill(QtCore.Qt.transparent)
            painter = QtGui.QPainter(pixmap)
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            painter.setPen(QtCore.Qt.NoPen)
            for index, color in enumerate(colors):
                painter.setBrush(QtGui.QColor(color))
                painter.drawEllipse(index * 12 + 1, 3, 9, 9)
            painter.end()
            self.icons[colors] = QtGui.QIcon(pixmap)
        return self.icons[colors]

    def attach(self, tree):
        if tree in self.trees:
            return True
        if tree.columnCount() != 3:
            return False  # Another extension owns additional columns.
        stretch = tree.header().stretchLastSection()
        original_width = tree.columnWidth(0)
        original_mode = tree.header().sectionResizeMode(0)
        original_description_hidden = tree.isColumnHidden(1)
        blocker, header_blocker = QtCore.QSignalBlocker(tree), QtCore.QSignalBlocker(tree.header())
        tree.setColumnCount(5)
        tree.setColumnHidden(
            1, True
        )  # Keep one visible Description column; preserve native Label2 data.
        tree.headerItem().setText(DESCRIPTION_COLUMN, "Description")
        tree.headerItem().setData(DESCRIPTION_COLUMN, QtCore.Qt.UserRole, MARKER)
        tree.setItemDelegateForColumn(DESCRIPTION_COLUMN, StatusDelegate(tree))
        tree.setColumnHidden(DESCRIPTION_COLUMN, False)
        tree.setColumnWidth(DESCRIPTION_COLUMN, 220)
        tree.headerItem().setText(COLUMN, "PDM status")
        tree.headerItem().setData(COLUMN, QtCore.Qt.UserRole, MARKER)
        tree.headerItem().setToolTip(
            COLUMN,
            "Blue: your checkout · Orange: other user · Green: released · Purple: newer revision · Teal: newer snapshot · Gray: unknown/stale",
        )
        delegate = StatusDelegate(tree)
        tree.setItemDelegateForColumn(COLUMN, delegate)
        tree.header().setStretchLastSection(False)
        tree.header().setSectionResizeMode(0, QtWidgets.QHeaderView.Interactive)
        tree.header().moveSection(tree.header().visualIndex(COLUMN), 1)
        tree.header().moveSection(tree.header().visualIndex(DESCRIPTION_COLUMN), 1)
        label_width = min(original_width, max(160, tree.viewport().width() // 2))
        tree.setColumnWidth(0, label_width)
        tree.setColumnWidth(COLUMN, max(170, tree.viewport().width() - label_width - 4))
        tree.setColumnHidden(COLUMN, False)
        self.trees[tree] = (
            stretch,
            delegate,
            original_width,
            original_mode,
            original_description_hidden,
        )
        del blocker, header_blocker
        return True

    def clear(self):
        for tree, (
            stretch,
            delegate,
            original_width,
            original_mode,
            original_description_hidden,
        ) in list(self.trees.items()):
            try:
                if (
                    tree.columnCount() >= 4
                    and tree.headerItem().data(COLUMN, QtCore.Qt.UserRole) == MARKER
                ):
                    blocker, header_blocker = (
                        QtCore.QSignalBlocker(tree),
                        QtCore.QSignalBlocker(tree.header()),
                    )
                    owns_description = (
                        tree.columnCount() > DESCRIPTION_COLUMN
                        and tree.headerItem().data(DESCRIPTION_COLUMN, QtCore.Qt.UserRole) == MARKER
                    )
                    description_delegate = (
                        tree.itemDelegateForColumn(DESCRIPTION_COLUMN) if owns_description else None
                    )
                    tree.setItemDelegateForColumn(COLUMN, None)
                    iterator = QtWidgets.QTreeWidgetItemIterator(tree)
                    while iterator.value():
                        item = iterator.value()
                        if tree.headerItem().data(DESCRIPTION_COLUMN, QtCore.Qt.UserRole) == MARKER:
                            item.setText(DESCRIPTION_COLUMN, "")
                        for role in (
                            QtCore.Qt.DisplayRole,
                            QtCore.Qt.DecorationRole,
                            QtCore.Qt.ToolTipRole,
                            QtCore.Qt.UserRole,
                        ):
                            item.setData(COLUMN, role, None)
                        iterator += 1
                    if (
                        tree.columnCount() == 5
                        and tree.headerItem().data(DESCRIPTION_COLUMN, QtCore.Qt.UserRole) == MARKER
                    ):
                        tree.setItemDelegateForColumn(DESCRIPTION_COLUMN, None)
                        tree.setColumnCount(3)
                    else:
                        tree.setColumnHidden(COLUMN, True)
                        if owns_description:
                            tree.setItemDelegateForColumn(DESCRIPTION_COLUMN, None)
                            tree.setColumnHidden(DESCRIPTION_COLUMN, True)
                    tree.setColumnHidden(1, original_description_hidden)
                    tree.setColumnWidth(0, original_width)
                    tree.header().setSectionResizeMode(0, original_mode)
                    tree.header().setStretchLastSection(stretch)
                    delegate.deleteLater()
                    if description_delegate is not None:
                        description_delegate.deleteLater()
                    del blocker, header_blocker
            except RuntimeError:
                pass  # Tree was destroyed by a workspace/layout change.
        self.trees.clear()
        self.icons.clear()

    def render(self, client, snapshot, stale=None):
        targets, rows = collect(client)
        documents = list(App.listDocuments().values())
        count, ambiguous = 0, 0
        window = Gui.getMainWindow()
        for tree in window.findChildren(QtWidgets.QTreeWidget):
            if tree.metaObject().className() != "Gui::TreeWidget" or not self.attach(tree):
                continue
            blocker = QtCore.QSignalBlocker(tree)

            def draw(item, key, reason=None):
                nonlocal count
                item.setText(DESCRIPTION_COLUMN, "")
                if key is None and reason is None:
                    item.setData(COLUMN, QtCore.Qt.DisplayRole, None)
                    item.setData(COLUMN, QtCore.Qt.DecorationRole, None)
                    item.setToolTip(COLUMN, "")
                    item.setData(COLUMN, QtCore.Qt.UserRole, None)
                    return
                target = targets.get(key, {})
                remote = (snapshot or {}).get("remote", {}).get(target.get("revision_id"))
                if (
                    remote
                    and remote.get("available")
                    and remote.get("item_id") != target.get("item_id")
                ):
                    remote, reason = None, "Local item/revision identity differs from the server."
                if target.get("foreign"):
                    remote, reason = None, "Document belongs to another server."
                description = target.get("description")
                if (
                    remote
                    and not target.get("dirty")
                    and target.get("description_token") != remote.get("description_token")
                ):
                    description = remote.get("description", description)
                if not reason and not target.get("foreign"):
                    item.setText(DESCRIPTION_COLUMN, description or "")
                local = dict((snapshot or {}).get("local", {}).get(key, {}))
                local["dirty"] = local.get("dirty", False) or target.get("dirty", False)
                presentation = pdm_status.describe(
                    remote,
                    local,
                    (snapshot or {}).get("checked_at"),
                    stale=None if reason else stale,
                )
                if reason:
                    label = (
                        "Ambiguous copy"
                        if key is None
                        else "Other server"
                        if target.get("foreign")
                        else "Identity mismatch"
                    )
                    presentation["text"] = label
                    presentation["badges"] = [
                        dict(kind="unknown", text=label, color=pdm_status.COLORS["unknown"])
                    ]
                    presentation["tooltip"] += "<br>" + escape(reason)
                item.setText(COLUMN, presentation["text"])
                item.setIcon(COLUMN, self.icon(presentation["badges"]))
                item.setToolTip(COLUMN, presentation["tooltip"])
                item.setData(COLUMN, QtCore.Qt.UserRole, presentation["badges"])
                count += 1

            def walk(item, document, parent=None):
                obj = object_for_item(item, document, parent) if document is not None else None
                draw(item, rows.get((obj.Document.Name, obj.Name)) if obj is not None else None)
                for index in range(item.childCount()):
                    child = item.child(index)
                    walk(child, obj.Document if obj is not None else document, obj)

            for index in range(tree.topLevelItemCount()):
                root = tree.topLevelItem(index)
                if root.type() != 1000:
                    continue
                document = document_for_item(root, documents)
                if document is None:
                    ambiguous += 1
                    draw(
                        root,
                        None,
                        "Document identity is ambiguous in the native tree; status is not guessed.",
                    )
                else:
                    draw(root, rows.get((document.Name, "")))
                for child in range(root.childCount()):
                    walk(root.child(child), document)
            del blocker
        return count, ambiguous


def session_key():
    client = Session.client
    if client is None or not client.token or client.is_expired():
        return None
    return id(client), client.token, (Session.user or {}).get("id")


class Controller:
    def __init__(self):
        self.column = Column()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ForgePDM-status")
        self.future, self.context = None, None
        self.key, self.generation = None, 0
        self.snapshot, self.hash_cache = None, {}
        self.pending, self.next_refresh, self.next_paint = False, 0, 0
        self.stale = None
        self.timer = QtCore.QTimer(Gui.getMainWindow())
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        QtWidgets.QApplication.instance().aboutToQuit.connect(self.close)

    def reset(self):
        self.generation += 1
        if self.context:
            self.context.cancelled.set()
        self.key = session_key()
        self.snapshot, self.hash_cache = None, {}
        self.stale = None
        self.column.clear()
        self.pending = self.key is not None
        self.next_refresh = self.next_paint = 0

    def request(self):
        self.generation += 1
        if self.context:
            self.context.cancelled.set()
        self.pending = True
        self.next_paint = 0
        self.stale = "Refreshing server status."

    def tick(self):
        try:
            self._tick()
        except Exception as error:
            # Presentation failure must never interrupt a CAD operation.
            self.stale = "Status display could not be refreshed."
            self.snapshot = None
            self.next_paint = monotonic() + 5
            App.Console.PrintWarning("ForgePDM status: {}\n".format(error))
            self.next_refresh = monotonic() + 60

    def _tick(self):
        current_key = session_key()
        if current_key != self.key:
            self.reset()
        if self.future is not None and self.future.done():
            future, request_key, generation = self.future, self.request_key, self.request_generation
            self.future, self.context = None, None
            if request_key == self.key and generation == self.generation:
                try:
                    self.snapshot = future.result()
                    self.stale = None
                except Exception as error:
                    self.stale = str(error)
                    if isinstance(error, ForgePDMError) and error.status == 401:
                        Session.invalidate()
                        self.reset()
                self.next_paint = 0
        if (
            self.key is None
            or Session.busy
            or QtWidgets.QApplication.activeModalWidget() is not None
        ):
            return
        now = monotonic()
        if now >= self.next_paint:
            stale = self.stale
            if self.snapshot and self.snapshot.get("checked_at"):
                checked = datetime.fromisoformat(self.snapshot["checked_at"])
                if (datetime.now(timezone.utc) - checked).total_seconds() > 90:
                    stale = stale or "Last successful check is more than 90 seconds old."
            self.column.render(Session.client, self.snapshot, stale)
            self.next_paint = now + 2
        if self.future is None and (self.pending or now >= self.next_refresh):
            targets, _ = collect(Session.client)
            captures = [value for value in targets.values() if not value["foreign"]]
            self.pending, self.next_refresh = False, now + 60
            if not captures:
                return
            self.context = Context()
            self.request_key, self.request_generation = self.key, self.generation
            request = Request(
                "Refreshing PDM status…",
                Session.client.fetch_tree_status,
                (captures, self.hash_cache),
            )
            self.future = self.executor.submit(request.execute, self.context)

    def close(self):
        self.timer.stop()
        if self.context:
            self.context.cancelled.set()
        self.column.clear()
        self.executor.shutdown(wait=False, cancel_futures=True)


def enable():
    global _controller
    if _controller is None:
        _controller = Controller()
    return _controller


def session_changed():
    if _controller is not None:
        _controller.reset()


def request_if_enabled():
    if _controller is not None:
        _controller.request()
