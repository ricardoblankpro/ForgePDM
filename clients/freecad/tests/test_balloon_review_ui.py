"""Real Qt coverage for read-only drawing diagnostics and viewport-only markers."""

import os
import sys
from types import SimpleNamespace as NS

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from freecad.forgepdm import balloon_review_ui as ui  # noqa: E402
from freecad.forgepdm.ui import QtCore, QtGui, QtWidgets  # noqa: E402


@pytest.fixture
def case(monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    parent = QtWidgets.QMainWindow()
    area = QtWidgets.QMdiArea()
    parent.setCentralWidget(area)
    scene = QtWidgets.QGraphicsScene()
    scene.setSceneRect(0, -2100, 2970, 2100)
    scene.setBackgroundBrush(QtGui.QColor("white"))
    view = QtWidgets.QGraphicsView(scene)
    view.setObjectName("PageView")
    window = area.addSubWindow(view)
    window.show()
    source = NS(TypeId="TechDraw::DrawViewPart", X=100, Y=100, getScale=lambda: 1)
    balloons = [
        NS(
            Name="Balloon" + str(i),
            Label="Balloon" + str(i),
            PDMBOMPosition=str(i),
            Text=str(i),
            X=10 * i,
            Y=10,
            SourceView=source,
        )
        for i in (1, 2)
    ]
    page = NS(
        Name="Page",
        Label="Drawing",
        Template=object(),
        isDerivedFrom=lambda t: t == "TechDraw::DrawPage",
        ViewObject=NS(show=lambda: None),
    )
    document = NS(
        Name="Assembly", Objects=[page], getObject=lambda n: page if n == page.Name else None
    )
    page.Document = document
    documents = {document.Name: document}
    observers, selection, calls = [], [], []
    freecad = NS(
        listDocuments=lambda: documents,
        addDocumentObserver=observers.append,
        removeDocumentObserver=observers.remove,
        setActiveDocument=lambda _: None,
        ParamGet=lambda _: NS(GetFloat=lambda *a: 10.0),
    )
    active_page = [page]
    gui = NS(
        activeDocument=lambda: NS(activeView=lambda: NS(getPage=lambda: active_page[0])),
        Selection=NS(clearSelection=selection.clear, addSelection=selection.append),
        runCommand=calls.append,
    )
    monkeypatch.setitem(sys.modules, "FreeCAD", freecad)
    monkeypatch.setitem(sys.modules, "FreeCADGui", gui)
    monkeypatch.setattr(ui.Session, "client", object())
    monkeypatch.setattr(ui.Session, "busy", False)
    rows = [dict(balloon=b, reason="View scale changed; retry Link BOM Balloon") for b in balloons]
    monkeypatch.setattr(ui.drawing_balloons, "diagnostics", lambda _: list(rows))
    dock = ui.ReviewDock(parent)
    parent.resize(1000, 700)
    parent.show()
    dock.set_document(document, page)
    dock.show()
    app.processEvents()
    yield NS(
        app=app,
        parent=parent,
        view=view,
        scene=scene,
        dock=dock,
        rows=rows,
        balloons=balloons,
        observers=observers,
        selection=selection,
        calls=calls,
        documents=documents,
        active_page=active_page,
    )
    dock.hide()
    parent.close()
    dock.deleteLater()
    parent.deleteLater()
    app.processEvents()


def test_numbered_markers_match_issue_list_and_click_selects_exact_balloon(case):
    dock = case.dock
    before = [vars(b).copy() for b in case.balloons]
    assert dock.list.count() == 2 and "2 balloons" in dock.summary.text()
    assert dock.markers.points == [(0, 1100, -1100), (1, 1200, -1100)]
    dock.list.setCurrentRow(1)
    assert case.selection == [case.balloons[1]]
    assert dock.markers.selected == 1
    assert "View scale changed" in dock.reason.text()
    assert [vars(b) for b in case.balloons] == before
    dock.repair()
    assert case.calls == ["ForgePDM_LinkBOMBalloon"]


def test_markers_are_not_part_of_drawing_scene_or_its_export(case):
    def render():
        result = QtGui.QImage(400, 300, QtGui.QImage.Format_ARGB32)
        result.fill(QtGui.QColor("white"))
        painter = QtGui.QPainter(result)
        case.scene.render(painter)
        painter.end()
        return result

    before = render()
    assert case.dock.markers.parent() is case.view.viewport()
    assert case.dock.markers.testAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
    case.dock.markers.hide()
    assert render() == before
    case.dock.markers.show()
    assert render() == before


def test_markers_are_visible_in_viewport_and_clear_without_leaving_old_marks(case):
    case.view.fitInView(case.scene.sceneRect(), QtCore.Qt.KeepAspectRatio)
    case.app.processEvents()
    highlighted = case.view.viewport().grab().toImage()
    case.dock.markers.hide()
    case.app.processEvents()
    clean = case.view.viewport().grab().toImage()
    assert highlighted != clean
    case.dock.markers.show()
    case.rows.clear()
    case.dock.refresh()
    case.app.processEvents()
    assert case.view.viewport().grab().toImage() == clean


def test_fixed_links_disappear_on_recheck_without_repairing_any_binding(case):
    case.dock.list.setCurrentRow(1)
    case.rows.pop(0)
    case.dock.dirty = True
    case.dock.poll()
    assert case.dock.list.count() == 1
    assert case.dock.selected_balloon() is case.balloons[1]
    case.rows.clear()
    case.dock.refresh()
    assert case.dock.list.count() == 0 and not case.dock.markers.points
    assert "pass validation" in case.dock.summary.text()
    assert not case.calls


def test_page_switch_document_close_and_panel_close_remove_markers(case):
    case.active_page[0] = NS(Name="OtherPage", Document=case.dock.document)
    case.dock.poll()
    assert case.dock.markers is None
    case.documents.clear()
    case.dock.poll()
    assert case.dock.list.count() == 0 and "closed" in case.dock.summary.text()
    case.dock.hide()
    assert not case.observers and not case.dock.timer.isActive()


def test_readonly_review_works_signed_out_but_link_button_requires_login(case, monkeypatch):
    case.dock.list.setCurrentRow(0)
    monkeypatch.setattr(ui.Session, "client", None)
    case.dock.poll()
    assert case.dock.markers.points and not case.dock.link.isEnabled()
    case.dock.repair()
    assert not case.calls


def test_missing_source_remains_in_list_without_a_misleading_marker(case):
    case.balloons[0].SourceView = None
    case.dock.refresh()
    assert case.dock.list.count() == 2
    assert case.dock.markers.points == [(1, 1200, -1100)]


def test_repair_does_not_switch_to_another_row_after_the_selected_problem_disappears(case):
    case.dock.list.setCurrentRow(0)
    case.rows.pop(0)
    case.dock.dirty = True
    case.dock.repair()
    assert case.dock.selected_balloon() is None
    assert not case.calls


def test_fresh_native_page_wrapper_still_maps_to_the_same_document_and_page(case):
    original = case.active_page[0]
    case.active_page[0] = NS(Name=original.Name, Document=NS(Name=original.Document.Name))
    case.dock.poll()
    assert case.dock.markers is not None
    case.active_page[0].Document.Name = "DifferentDocument"
    case.dock.poll()
    assert case.dock.markers is None
