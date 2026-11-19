"""Real Qt column customization, durable row text and in-dialog fit errors."""

import json
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from freecad.forgepdm import drawing_bom_ui as ui  # noqa: E402
from freecad.forgepdm.ui import QtWidgets  # noqa: E402


@pytest.fixture
def case(monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    values = {}
    parameters = SimpleNamespace(
        GetString=lambda key, default: values.get(key, default),
        SetString=lambda key, value: values.update({key: value}),
    )
    monkeypatch.setattr(ui.settings, "_parameters", lambda: parameters)
    report = {
        "revision_id": "assembly",
        "item_number": "A000001",
        "revision_label": "A",
        "lines": [
            {
                "component_revision_id": "part",
                "position": 5,
                "item_number": "P000001",
                "revision_label": "A",
                "quantity": "2",
                "description": "Steel plate",
            }
        ],
    }
    page = SimpleNamespace(
        Label="Drawing", Views=[], Template=SimpleNamespace(Width=297, Height=210)
    )
    dialog = ui.DrawingBOMDialog(None, report, [page])
    dialog.show()
    app.processEvents()
    yield app, dialog, values
    dialog.reject()
    dialog.deleteLater()
    app.processEvents()


def test_custom_text_survives_column_reordering_and_presets_do_not_store_row_text(
    case, monkeypatch
):
    _, dialog, values = case
    dialog.title.setText("Lista de peças — {item_number}")
    dialog.add_column()
    dialog.grid.item(0, 5).setText("Paint blue")
    dialog.columns.setCurrentCell(5, 1)
    dialog.move(-1)
    assert dialog.grid.item(0, 4).text() == "Paint blue"
    monkeypatch.setattr(QtWidgets.QInputDialog, "getText", lambda *args: ("Fabrication", True))
    dialog.save_layout()
    assert "Fabrication" in json.loads(values["DrawingBOMLayouts"])
    saved = json.loads(values["DrawingBOMLayouts"])["Fabrication"]
    assert saved["title"] == "Lista de peças — {item_number}"
    dialog.title.clear()
    dialog.load_layout(saved)
    assert dialog.title.text() == saved["title"]
    assert "Paint blue" not in values["DrawingBOMLayouts"]
    dialog.accept()
    assert dialog.result() == 1
    assert list(dialog.notes.values())[0]


def test_existing_table_title_is_loaded_for_update(case):
    _, dialog, _ = case
    definition = {**dialog.definition(), "title": "Lista de materiais"}
    table = SimpleNamespace(
        Label="BOM",
        PDMTableData=json.dumps(
            {"format": 1, "report": dialog.report, "layout": definition, "notes": {}}
        ),
        X=140,
        Y=50,
    )
    page = dialog.page.currentData()
    page.Views.append(table)
    dialog.page_changed()
    dialog.target.setCurrentIndex(1)
    assert dialog.title.text() == "Lista de materiais"
    assert dialog.definition()["title"] == "Lista de materiais"


def test_invalid_page_fit_and_width_stay_in_editor(case):
    _, dialog, _ = case
    dialog.x.setValue(1)
    dialog.accept()
    assert dialog.result() == 0 and "does not fit" in dialog.status.text()
    dialog.columns.item(0, 2).setText("nan")
    dialog.accept()
    assert dialog.result() == 0 and "width" in dialog.status.text()


def test_view_switch_preserves_layout_and_isolates_custom_notes(case, monkeypatch):
    _, previous, values = case
    report = {**previous.report, "structure_complete": True}
    direct = {**report["lines"][0], "row_key": "direct:part", "quantity_per_parent": "2"}
    nested = {**direct, "row_key": "nested:part", "position": "1.5", "quantity": "6", "level": 2}
    flat = {**direct, "row_key": "flat:part", "quantity": "6"}
    report["views"] = {"direct": [direct], "indented": [nested], "flattened": [flat]}
    dialog = ui.DrawingBOMDialog(None, report, previous.pages)
    try:
        dialog.title.setText("Lista de peças")
        dialog.add_column()
        dialog.grid.item(0, 5).setText("Direct only")
        dialog.view.setCurrentIndex(1)
        assert dialog.definition()["view"] == "indented"
        assert dialog.grid.item(0, 0).text() == "1.5"
        assert dialog.grid.item(0, 5).text() == ""
        dialog.view.setCurrentIndex(2)
        assert dialog.grid.item(0, 3).text() == "6"
        assert dialog.grid.item(0, 5).text() == ""
        dialog.grid.item(0, 5).setText("Flattened only")
        monkeypatch.setattr(QtWidgets.QInputDialog, "getText", lambda *args: ("Flat layout", True))
        dialog.save_layout()
        saved = json.loads(values["DrawingBOMLayouts"])["Flat layout"]
        assert saved["view"] == "flattened" and saved["title"] == "Lista de peças"
        dialog.view.setCurrentIndex(0)
        assert dialog.grid.item(0, 5).text() == "Direct only"
        dialog.load_layout(saved)
        assert dialog.view.currentData() == "flattened"
        assert dialog.grid.item(0, 5).text() == "Flattened only"
    finally:
        dialog.reject()
        dialog.deleteLater()


def multirow_report(dialog):
    value = dict(dialog.source_report)
    value["lines"] = [
        {
            **value["lines"][0],
            "component_revision_id": key,
            "position": position,
            "item_number": number,
            "quantity": quantity,
        }
        for key, position, number, quantity in [
            ("p10", 1, "P10", "10"),
            ("p2", 10, "P2", "2"),
            ("p1", 2, "P1", "1.5"),
        ]
    ]
    return value


def test_sort_controls_default_and_presets_retain_choice_without_row_text(case, monkeypatch):
    _, previous, values = case
    dialog = ui.DrawingBOMDialog(None, multirow_report(previous), previous.pages)
    try:
        assert dialog.sort_by.currentData() == "item_number"
        assert [dialog.grid.item(i, 1).text() for i in range(3)] == ["P1", "P2", "P10"]
        dialog.add_column()
        dialog.grid.item(0, 5).setText("Note on P1")
        dialog.sort_by.setCurrentIndex(dialog.sort_by.findData("quantity"))
        dialog.sort_order.setCurrentIndex(dialog.sort_order.findData("descending"))
        assert [dialog.grid.item(i, 1).text() for i in range(3)] == ["P10", "P2", "P1"]
        assert dialog.grid.item(2, 5).text() == "Note on P1"
        monkeypatch.setattr(QtWidgets.QInputDialog, "getText", lambda *args: ("Sorted", True))
        dialog.save_layout()
        saved = json.loads(values["DrawingBOMLayouts"])["Sorted"]
        assert saved["sort_by"] == "quantity" and saved["sort_order"] == "descending"
        assert "Note on P1" not in values["DrawingBOMLayouts"]
        dialog.load_layout(saved)
        assert dialog.grid.item(2, 5).text() == "Note on P1"
        assert dialog.report == multirow_report(previous)
        dialog.sort_by.setCurrentIndex(dialog.sort_by.findData("bom_order"))
        assert not dialog.sort_order.isEnabled()
        assert [dialog.grid.item(i, 1).text() for i in range(3)] == ["P10", "P2", "P1"]
    finally:
        dialog.reject()
        dialog.deleteLater()


def test_saved_table_sort_loads_and_legacy_table_keeps_original_order(case):
    _, previous, _ = case
    report = multirow_report(previous)
    page = SimpleNamespace(
        Label="Sort QA", Views=[], Template=SimpleNamespace(Width=297, Height=210)
    )
    definition = previous.definition()
    legacy = {k: v for k, v in definition.items() if k not in ("sort_by", "sort_order")}
    for name, layout, version in [
        ("Legacy", legacy, 1),
        ("Sorted", {**definition, "sort_by": "item_number", "sort_order": "descending"}, 4),
    ]:
        page.Views.append(
            SimpleNamespace(
                Label=name,
                PDMTableData=json.dumps(
                    dict(format=version, report=report, layout=layout, notes={})
                ),
                X=140,
                Y=50,
            )
        )
    dialog = ui.DrawingBOMDialog(None, report, [page])
    try:
        dialog.target.setCurrentIndex(1)
        assert dialog.sort_by.currentData() == "bom_order"
        assert [dialog.grid.item(i, 1).text() for i in range(3)] == ["P10", "P2", "P1"]
        dialog.target.setCurrentIndex(2)
        assert (
            dialog.sort_by.currentData() == "item_number"
            and dialog.sort_order.currentData() == "descending"
        )
        assert [dialog.grid.item(i, 1).text() for i in range(3)] == ["P10", "P2", "P1"]
    finally:
        dialog.reject()
        dialog.deleteLater()
