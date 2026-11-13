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
    dialog.add_column()
    dialog.grid.item(0, 5).setText("Paint blue")
    dialog.columns.setCurrentCell(5, 1)
    dialog.move(-1)
    assert dialog.grid.item(0, 4).text() == "Paint blue"
    monkeypatch.setattr(QtWidgets.QInputDialog, "getText", lambda *args: ("Fabrication", True))
    dialog.save_layout()
    assert "Fabrication" in json.loads(values["DrawingBOMLayouts"])
    assert "Paint blue" not in values["DrawingBOMLayouts"]
    dialog.accept()
    assert dialog.result() == 1
    assert list(dialog.notes.values())[0]


def test_invalid_page_fit_and_width_stay_in_editor(case):
    _, dialog, _ = case
    dialog.x.setValue(1)
    dialog.accept()
    assert dialog.result() == 0 and "does not fit" in dialog.status.text()
    dialog.columns.item(0, 2).setText("nan")
    dialog.accept()
    assert dialog.result() == 0 and "width" in dialog.status.text()
