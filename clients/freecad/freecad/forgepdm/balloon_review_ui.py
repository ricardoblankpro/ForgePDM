"""Modeless issue list and viewport-only markers; no native graphics-item access."""

from . import balloon_review, drawing_balloons
from .session import Session
from .ui import QtCore, QtGui, QtWidgets

_dock = None


class Markers(QtWidgets.QWidget):
    """Paint outside the drawing scene, so diagnostic marks cannot enter a PDF."""

    def __init__(self, view):
        super().__init__(view.viewport())
        self.view, self.points, self.selected = view, [], -1
        self.setObjectName("ForgePDMBalloonProblemMarkers")
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground)
        view.viewport().installEventFilter(self)
        self.setGeometry(view.viewport().rect())
        self.show()

    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.Resize:
            self.setGeometry(watched.rect())
        if event.type() in (QtCore.QEvent.Paint, QtCore.QEvent.Resize, QtCore.QEvent.Wheel):
            self.update()
        return False

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        for index, x, y in self.points:
            center = self.view.mapFromScene(QtCore.QPointF(x, y))
            radius = 15 if index == self.selected else 12
            painter.setPen(QtGui.QPen(QtGui.QColor("#d62424"), 3))
            painter.setBrush(QtGui.QColor(255, 220, 120, 45))
            painter.drawEllipse(center, radius, radius)
            badge = QtCore.QRect(
                center.x() + 8, center.y() - 24, max(19, 8 + 8 * len(str(index + 1))), 19
            )
            painter.setBrush(QtGui.QColor("#b91c1c"))
            painter.drawEllipse(badge)
            painter.setPen(QtGui.QColor("white"))
            painter.drawText(badge, QtCore.Qt.AlignCenter, str(index + 1))
        painter.end()


class ReviewObserver:
    def __init__(self, dock):
        self.dock = dock

    def changed(self, document):
        if document is self.dock.document:
            self.dock.dirty = True

    def slotChangedObject(self, obj, _property):
        self.changed(obj.Document)

    def slotDeletedObject(self, obj):
        self.changed(obj.Document)

    def slotRecomputedDocument(self, document):
        self.changed(document)

    slotUndoDocument = slotRecomputedDocument
    slotRedoDocument = slotRecomputedDocument
    slotDeletedDocument = slotRecomputedDocument


class ReviewDock(QtWidgets.QDockWidget):
    def __init__(self, parent):
        super().__init__("BOM balloon problems", parent)
        self.setObjectName("ForgePDMBalloonProblems")
        self.document, self.page, self.markers = None, None, None
        self.document_name = None
        self.dirty, self.rows, self.observing = True, [], False
        self.observer = ReviewObserver(self)
        self.setMinimumWidth(320)
        body = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(body)
        self.pages = QtWidgets.QComboBox()
        self.pages.currentIndexChanged.connect(self.choose_page)
        layout.addWidget(self.pages)
        self.summary = QtWidgets.QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.list = QtWidgets.QListWidget()
        self.list.setWordWrap(True)
        self.list.currentRowChanged.connect(self.locate)
        layout.addWidget(self.list)
        self.reason = QtWidgets.QLabel()
        self.reason.setWordWrap(True)
        self.reason.setTextFormat(QtCore.Qt.PlainText)
        layout.addWidget(self.reason)
        buttons = QtWidgets.QHBoxLayout()
        self.recheck = QtWidgets.QPushButton("Recheck")
        self.recheck.clicked.connect(self.refresh)
        self.link = QtWidgets.QPushButton("Link selected…")
        self.link.clicked.connect(self.repair)
        buttons.addWidget(self.recheck)
        buttons.addWidget(self.link)
        layout.addLayout(buttons)
        label = QtWidgets.QLabel("Red numbers match this list. Close the panel to hide the marks.")
        label.setWordWrap(True)
        layout.addWidget(label)
        self.setWidget(body)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.poll)
        self.visibilityChanged.connect(self.visibility)
        parent.addDockWidget(QtCore.Qt.RightDockWidgetArea, self)
        tasks = parent.findChild(QtWidgets.QDockWidget, "Tasks")
        if tasks is not None:
            parent.tabifyDockWidget(tasks, self)

    def visibility(self, visible):
        import FreeCAD as App

        if visible:
            if not self.observing:
                App.addDocumentObserver(self.observer)
                self.observing = True
            self.dirty = True
            self.timer.start()
        else:
            self.timer.stop()
            if self.observing:
                App.removeDocumentObserver(self.observer)
                self.observing = False
            self.clear_markers()

    def set_document(self, document, preferred=None):
        self.clear_markers()
        self.document = document
        self.document_name = document.Name
        self.pages.blockSignals(True)
        self.pages.clear()
        for page in document.Objects:
            if page.isDerivedFrom("TechDraw::DrawPage") and page.Template:
                self.pages.addItem(page.Label, page.Name)
        self.pages.blockSignals(False)
        if preferred is not None:
            index = self.pages.findData(preferred.Name)
            if index >= 0:
                self.pages.setCurrentIndex(index)
        self.page = document.getObject(self.pages.currentData()) if self.pages.count() else None
        self.dirty = True
        self.refresh()

    def choose_page(self, *_):
        if self.document is None:
            return
        self.page = self.document.getObject(self.pages.currentData())
        if self.page is not None:
            import FreeCAD as App

            App.setActiveDocument(self.document.Name)
            self.page.ViewObject.show()
        self.dirty = True
        self.refresh()

    def current_document(self):
        import FreeCAD as App

        return (
            self.document is not None
            and App.listDocuments().get(self.document_name) is self.document
        )

    def poll(self):
        if not self.current_document():
            self.document, self.page = None, None
            self.rows = []
            self.list.clear()
            self.summary.setText("The drawing document was closed.")
            self.link.setEnabled(False)
            self.clear_markers()
            return
        self.link.setEnabled(
            self.selected_balloon() is not None and Session.client is not None and not Session.busy
        )
        self.link.setToolTip(
            "Log in to ForgePDM to repair links."
            if Session.client is None
            else "Review and relink this balloon."
        )
        if (
            Session.busy
            or getattr(self.document, "HasPendingTransaction", False)
            or QtWidgets.QApplication.mouseButtons()
            or QtCore.QThreadPool.globalInstance().activeThreadCount()
        ):
            return
        if self.dirty:
            self.refresh()
        else:
            self.update_markers()

    def refresh(self, *_):
        if not self.current_document():
            return
        self.dirty = False
        selected = self.selected_balloon()
        self.page = (
            self.document.getObject(self.pages.currentData()) if self.pages.count() else None
        )
        self.rows = drawing_balloons.diagnostics(self.page) if self.page is not None else []
        self.list.blockSignals(True)
        self.list.clear()
        for i, row in enumerate(self.rows):
            reason = row["reason"].partition("; retry Link BOM Balloon")[0]
            item = QtWidgets.QListWidgetItem(
                "{}. {}\n{}".format(i + 1, balloon_review.caption(row["balloon"]), reason)
            )
            item.setToolTip(row["reason"])
            self.list.addItem(item)
        self.list.blockSignals(False)
        count = len(self.rows)
        self.summary.setText(
            "{} balloon{} need attention. Click a row to locate it on the page.".format(
                count, "s" if count != 1 else ""
            )
            if count
            else "All linked balloons on this page pass validation."
        )
        if self.page is None:
            self.summary.setText(
                "The drawing page was removed. Reopen Check BOM Balloons to choose another page."
            )
        index = next((i for i, row in enumerate(self.rows) if row["balloon"] is selected), -1)
        if index >= 0:
            self.list.setCurrentRow(index)
        else:
            self.reason.clear()
        self.link.setEnabled(index >= 0 and Session.client is not None and not Session.busy)
        self.update_markers()

    def selected_balloon(self):
        index = self.list.currentRow()
        return self.rows[index]["balloon"] if 0 <= index < len(self.rows) else None

    def locate(self, index):
        if not 0 <= index < len(self.rows) or not self.current_document():
            self.link.setEnabled(False)
            return
        import FreeCAD as App
        import FreeCADGui as Gui

        balloon = self.rows[index]["balloon"]
        App.setActiveDocument(self.document.Name)
        self.page.ViewObject.show()
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(balloon)
        self.reason.setText(self.rows[index]["reason"])
        self.link.setEnabled(Session.client is not None and not Session.busy)
        self.update_markers()

    def repair(self):
        if Session.busy or Session.client is None or self.selected_balloon() is None:
            return
        selected = self.selected_balloon()
        if self.dirty:
            self.refresh()
            if self.selected_balloon() is not selected:
                return
        self.locate(self.list.currentRow())
        import FreeCADGui as Gui

        Gui.runCommand("ForgePDM_LinkBOMBalloon")
        self.dirty = True

    def active_view(self):
        import FreeCADGui as Gui

        document = Gui.activeDocument()
        if document is None:
            return None
        active = document.activeView()
        if not hasattr(active, "getPage"):
            return None
        page = active.getPage()
        # MDIViewPagePy can return a fresh Python wrapper for the same page.
        if page.Name != self.page.Name or page.Document.Name != self.document_name:
            return None
        area = self.parent().findChild(QtWidgets.QMdiArea)
        window = area.activeSubWindow() if area else None
        return (
            window.findChild(QtWidgets.QGraphicsView, self.page.Name + "View") if window else None
        )

    def clear_markers(self):
        if self.markers is not None:
            try:
                self.markers.hide()
                self.markers.deleteLater()
            except RuntimeError:
                pass  # The native page viewport may already have been closed.
            self.markers = None

    def update_markers(self):
        view = self.active_view() if self.page is not None else None
        try:
            if self.markers is not None and self.markers.view is not view:
                self.clear_markers()
        except RuntimeError:
            self.markers = None
        if view is None:
            return
        if self.markers is None:
            self.markers = Markers(view)
        import FreeCAD as App

        resolution = App.ParamGet("User parameter:BaseApp/Preferences/Mod/TechDraw/Rez").GetFloat(
            "Resolution", 10.0
        )
        points = []
        for i, row in enumerate(self.rows):
            try:
                x, y = balloon_review.page_position(row["balloon"])
                points.append((i, x * resolution, -y * resolution))
            except (ValueError, AttributeError, RuntimeError):
                continue
        self.markers.points = points
        self.markers.selected = self.list.currentRow()
        self.markers.update()
        self.markers.raise_()


def show_review(parent, document, preferred=None):
    global _dock
    if _dock is None:
        _dock = ReviewDock(parent)
    _dock.set_document(document, preferred)
    _dock.show()
    _dock.raise_()
    return _dock
