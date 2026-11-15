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
