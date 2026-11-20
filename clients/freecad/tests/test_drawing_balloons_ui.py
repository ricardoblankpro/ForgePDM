"""Real Qt adoption requires an explicit frozen entry selection."""

import json
import os
from types import SimpleNamespace as NS

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from freecad.forgepdm import drawing_balloons_ui as ui, drawing_bom as bom  # noqa: E402
from freecad.forgepdm.ui import QtWidgets  # noqa: E402


@pytest.fixture
def case():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    report = dict(
        revision_id="root",
        view="direct",
        lines=[
            dict(
                component_revision_id=part,
                position=pos,
                item_number=part,
                revision_label="A",
                description="Plate",
            )
            for part, pos in [("P10", 5), ("P2", 8)]
        ],
    )
    table = NS(
        Label="BOM",
        PDMTableData=json.dumps(dict(format=4, layout=bom.DEFAULT, notes={}, report=report)),
        isDerivedFrom=lambda _: False,
    )
    balloon = NS(
        Label="Balloon",
        Text="literal",
        isDerivedFrom=lambda kind: kind == "TechDraw::DrawViewBalloon",
    )
    page = NS(Label="Drawing", Views=[table, balloon])
    dialog = ui.LinkBalloonDialog(None, [page], balloon)
    yield dialog, table, balloon
    dialog.deleteLater()
    app.processEvents()


def test_entry_selection_is_explicit_and_matches_table_sort(case):
    dialog, _, _ = case
    assert [dialog.grid.item(i, 1).text() for i in range(2)] == ["P2", "P10"]
    dialog.accept()
    assert dialog.result() == 0 and "Select" in dialog.status.text()
    dialog.grid.selectRow(1)
    assert dialog.row_key() == "P10:5"
    dialog.accept()
    assert dialog.result() == 1


def test_non_direct_table_is_explained_and_cannot_be_adopted(case):
    dialog, table, _ = case
    data = json.loads(table.PDMTableData)
    data["report"]["view"] = data["layout"]["view"] = "flattened"
    table.PDMTableData = json.dumps(data)
    dialog.table_changed()
    assert not dialog.rows and "Direct" in dialog.status.text()
    dialog.accept()
    assert dialog.result() == 0


def test_existing_unresolved_balloon_requires_reselection_and_cancel_preserves_data(case):
    dialog, table, balloon = case
    balloon.PDMBOMTable = table
    balloon.PDMBOMStatus = "Unresolved: missing entry"
    before = table.PDMTableData, balloon.Text
    dialog.balloon_changed()
    assert "Unresolved" in dialog.status.text()
    assert dialog.grid.currentRow() == -1
    dialog.reject()
    assert (table.PDMTableData, balloon.Text) == before
