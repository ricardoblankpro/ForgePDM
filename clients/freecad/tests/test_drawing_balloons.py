"""Frozen identity resolution and safe reconciliation, independent of FreeCAD."""

import copy
import json
from types import SimpleNamespace as NS

import pytest

from freecad.forgepdm import drawing_balloons as balloons, drawing_bom as bom


@pytest.fixture
def data():
    return dict(
        format=4,
        layout=bom.layout(bom.DEFAULT),
        notes={},
        report=dict(
            revision_id="assembly-A",
            view="direct",
            item_number="A1",
            revision_label="A",
            token="frozen",
            lines=[
                dict(
                    component_revision_id="part-A",
                    position=5,
                    item_number="P10",
                    revision_label="A",
                    description="Plate",
                    quantity="2",
                ),
                dict(
                    component_revision_id="other-A",
                    position=8,
                    item_number="P2",
                    revision_label="A",
                    description="Pin",
                    quantity="1",
                ),
            ],
        ),
    )


def test_sort_localization_quantity_and_recreated_line_ids_preserve_exact_link(data):
    binding = balloons.identity(data, data["report"]["lines"][0])
    data["report"].update(token="new", language="pt-BR")
    line = data["report"]["lines"][0]
    line.update(id="recreated-db-line", description="Chapa", quantity="20")
    data["layout"]["sort_order"] = "descending"
    data["report"]["lines"].reverse()
    assert balloons.resolve(binding, data) is line
    assert binding["position"] == 5
    assert [row["position"] for row in balloons.entries(data)] == [5, 8]


@pytest.mark.parametrize(
    "change", ["revision", "position", "root", "removed", "duplicate", "view", "reused_position"]
)
def test_identity_changes_require_explicit_reconciliation(data, change):
    binding = balloons.identity(data, data["report"]["lines"][0])
    line = data["report"]["lines"][0]
    if change == "revision":
        line["component_revision_id"] = "part-B"
    elif change == "position":
        line["position"] = 7
    elif change == "root":
        data["report"]["revision_id"] = "assembly-B"
    elif change == "removed":
        data["report"]["lines"].pop(0)
    elif change == "duplicate":
        data["report"]["lines"].append({**line, "position": 10})
    elif change == "view":
        data["report"]["view"] = "flattened"
    else:
        line.update(component_revision_id="new-A", position=5)
    with pytest.raises(ValueError):
        balloons.resolve(binding, data)


def test_duplicate_occurrences_are_distinct_and_merging_never_retargets(data):
    row = data["report"]["lines"][0]
    duplicate = {**row, "position": 10}
    data["report"]["lines"].append(duplicate)
    first = balloons.identity(data, row)
    second = balloons.identity(data, duplicate)
    assert balloons.resolve(first, data) is row
    assert balloons.resolve(second, data) is duplicate
    data["report"]["lines"].remove(duplicate)
    with pytest.raises(ValueError):
        balloons.resolve(first, data)
    with pytest.raises(ValueError):
        balloons.resolve(second, data)


@pytest.mark.parametrize("change", ["key", "position", "missing_root", "bad_position"])
def test_ambiguous_or_legacy_missing_identity_is_rejected(data, change):
    if change == "key":
        for line in data["report"]["lines"]:
            line["row_key"] = "same"
    elif change == "position":
        data["report"]["lines"][1]["position"] = 5
    elif change == "bad_position":
        data["report"]["lines"][0]["position"] = "5"
    else:
        del data["report"]["revision_id"]
    with pytest.raises(ValueError):
        balloons.entries(data)


class Balloon:
    Label = "Balloon"
    Text = "old literal"
    ExpressionEngine = []
    PDMBOMStatus = "Linked"

    def __init__(self, data, table):
        self.PDMBOMTable = table
        self.PDMBOMBinding = json.dumps(balloons.identity(data, data["report"]["lines"][0]))
        self.PDMBOMPosition = "5"
        self.PropertiesList = list(balloons.PROPERTIES)
        self.ExpressionEngine = [("Text", balloons.EXPRESSION)]

    def getTypeIdOfProperty(self, name):
        return balloons.PROPERTIES[name]

    def setExpression(self, name, expression):
        self.ExpressionEngine = [(name, expression)]

    def isDerivedFrom(self, kind):
        return kind == "TechDraw::DrawViewBalloon"


def test_updates_are_table_scoped_and_unresolved_links_stay_unresolved(data):
    table, other = object(), object()
    balloon, unaffected = Balloon(data, table), Balloon(data, other)
    document = NS(Objects=[balloon, unaffected])
    data["report"]["lines"][0]["position"] = 7
    balloons.refresh(document, table, data)
    assert balloon.PDMBOMPosition == "?" and balloon.PDMBOMStatus.startswith("Unresolved")
    assert unaffected.PDMBOMPosition == "5" and unaffected.PDMBOMStatus == "Linked"
    data["report"]["lines"][0]["position"] = 5
    balloons.refresh(document, table, data)
    assert balloon.PDMBOMPosition == "?"


@pytest.mark.parametrize(
    "damage", ["orphan", "expression", "text", "binding", "page", "status", "position", "format"]
)
def test_pdf_preflight_rejects_damaged_links_without_rewriting_them(data, damage):
    data["format"] = 5
    table = NS(PDMTableData=json.dumps(data))
    balloon = Balloon(data, table)
    balloon.Text = "5"
    source = object()
    page = NS(Views=[table, balloon, source])
    document = NS(Objects=[table, balloon, source])
    page.Document = balloon.Document = table.Document = document
    balloon.SourceView = source
    assert balloons.issues(page) == []
    if damage == "orphan":
        balloon.PDMBOMTable = None
    elif damage == "expression":
        balloon.ExpressionEngine = []
    elif damage == "text":
        balloon.Text = "8"
    elif damage == "binding":
        balloon.PDMBOMBinding = "{invalid"
    elif damage == "page":
        page.Views.remove(table)
    elif damage == "status":
        balloon.PDMBOMStatus = "Unresolved"
    elif damage == "position":
        balloon.PDMBOMPosition = "8"
    else:
        table.PDMTableData = json.dumps({**data, "format": 4})
    before = copy.copy(balloon.__dict__)
    assert len(balloons.issues(page)) == 1
    diagnostic = balloons.diagnostics(page)
    assert len(diagnostic) == 1 and diagnostic[0]["balloon"] is balloon
    assert balloons.issues(page) == [balloon.Label + ": " + diagnostic[0]["reason"]]
    assert balloon.__dict__ == before


def test_format5_keeps_all_table_evidence(data):
    data["format"] = 5
    obj = NS(PDMTableData=json.dumps(data))
    assert bom.read_table(obj) == data
    assert obj.PDMTableData == json.dumps(data)


def test_stable_binding_resolves_same_frozen_identity_and_keeps_format7(data):
    data["format"] = 7
    binding = dict(balloons.identity(data, data["report"]["lines"][0]), format=3, attachment={})
    assert balloons.resolve(binding, data) is data["report"]["lines"][0]
    obj = NS(PDMTableData=json.dumps(data))
    assert bom.read_table(obj) == data


@pytest.mark.parametrize("damage", [None, "view", "revision", "miss", "unresolved", "position"])
def test_explicit_legacy_rebaseline_retains_target_or_rejects_changes(data, monkeypatch, damage):
    from freecad.forgepdm import balloon_geometry as geometry
    from freecad.forgepdm.geometry_fingerprint import PROFILE

    data["format"] = 6
    table = NS(PDMTableData=json.dumps(data))
    balloon = Balloon(data, table)
    source = object()
    document = NS(Objects=[table, balloon, source])
    page = NS(Document=document, Views=[table, balloon, source])
    balloon.Document = table.Document = document
    balloon.SourceView, balloon.Text = source, "5"
    rid = data["report"]["lines"][0]["component_revision_id"]
    old = dict(view="View", origin=[1, 2], components=[["Part", rid, "old-raw-hash"]])
    binding = dict(
        json.loads(balloon.PDMBOMBinding), format=2, attachment=dict(component="Part", geometry=old)
    )
    balloon.PDMBOMBinding = json.dumps(binding)
    current = dict(old, fingerprint=PROFILE, components=[["Part", rid, "stable-hash"]])
    hits = [(NS(Name="Part"), rid)]
    if damage == "view":
        current["origin"] = [2, 2]
    elif damage == "revision":
        current["components"] = [["Part", "different", "stable-hash"]]
    elif damage == "miss":
        hits.clear()
    elif damage == "unresolved":
        balloon.PDMBOMStatus = "Unresolved"
    elif damage == "position":
        balloon.PDMBOMPosition = "8"
    monkeypatch.setattr(geometry, "evidence", lambda _: current)
    monkeypatch.setattr(geometry, "pick", lambda _: hits)
    before = copy.copy(balloon.__dict__)
    if damage:
        with pytest.raises(ValueError):
            balloons.plan_legacy_upgrade(page, balloon)
    else:
        upgraded = balloons.plan_legacy_upgrade(page, balloon)
        assert upgraded["format"] == 3 and upgraded["attachment"]["component"] == "Part"
        assert balloons.resolve(upgraded, data) is data["report"]["lines"][0]
    assert balloon.__dict__ == before


@pytest.mark.parametrize(
    "damage",
    [None, "other_page", "foreign_source", "foreign_group", "arbitrary_container", "missing"],
)
def test_projection_group_source_is_valid_only_through_its_own_page(data, damage):
    data["format"] = 5
    document = NS()
    source = NS(Name="Front", TypeId="TechDraw::DrawProjGroupItem", Document=document)
    group = NS(
        TypeId="TechDraw::DrawProjGroup",
        Document=document,
        Views=[NS(Name=source.Name, Document=document)],
    )
    table = NS(PDMTableData=json.dumps(data), Document=document)
    balloon = Balloon(data, table)
    balloon.Document = document
    balloon.SourceView = source
    balloon.Text = "5"
    page = NS(Document=document, Views=[group, table, balloon])
    if damage == "other_page":
        page.Views.remove(group)
    elif damage == "foreign_source":
        source.Document = NS()
    elif damage == "foreign_group":
        group.Document = NS()
    elif damage == "arbitrary_container":
        group.TypeId = "App::DocumentObjectGroup"
    elif damage == "missing":
        balloon.SourceView = None
    before = table.PDMTableData, balloon.PDMBOMBinding, balloon.Text
    if damage is None:
        balloons.validate_target(document, page, balloon, table)
        assert balloons.issues(page) == []
    else:
        with pytest.raises(ValueError, match="same page"):
            balloons.validate_target(document, page, balloon, table)
        assert balloons.issues(page)
    assert (table.PDMTableData, balloon.PDMBOMBinding, balloon.Text) == before
