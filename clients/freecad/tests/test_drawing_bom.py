"""Frozen tables, custom columns, precision and safe standalone SVG."""

import copy
from xml.etree import ElementTree as ET

import pytest

from freecad.forgepdm import drawing_bom as bom


def report():
    return {
        "item_number": "A000001",
        "revision_label": "A",
        "lines": [
            {
                "component_revision_id": "child-A",
                "position": 5,
                "item_number": "P000001",
                "revision_label": "A",
                "quantity": "2",
                "description": "STEEL <3 mm> & zinc",
                "unit_mass": "0.0000001",
                "total_mass": "0.0000002",
                "mass_source": {"status": "cad_estimate"},
            }
        ],
    }


def test_svg_is_self_contained_escaped_and_preserves_direct_positions():
    value = report()
    before = copy.deepcopy(value)
    svg, w, h = bom.render(value, bom.DEFAULT, {})
    ET.fromstring(svg)
    assert "&lt;" in svg and "&amp;" in svg
    assert "P000001" in svg and ">5<" in svg
    assert "http:" not in svg.replace('xmlns="http://www.w3.org/2000/svg"', "")
    assert 0 < h < 200 and w == 175
    assert value == before
    assert "Stored direct EBOM" not in svg and "CAD estimate" not in svg
    assert (
        bom.cell(
            {"item_number": "S000001", "item_name": "M12 ISO4016", "description": ""},
            {"field": "description"},
            {},
            3,
        )
        == "M12 ISO4016"
    )


def test_custom_text_follows_component_revision_position_not_row_order():
    value = report()
    definition = bom.layout(bom.DEFAULT)
    definition["columns"].append(
        {
            "field": "custom",
            "heading": "Finish",
            "width": 25,
            "align": "left",
            "key": "finish",
            "unit": "kg",
        }
    )
    notes = {bom.row_key(value["lines"][0]): {"finish": "Paint <blue>"}}
    svg, _, _ = bom.render(value, definition, notes)
    assert "Paint" in svg
    value["lines"][0]["quantity"] = "12"
    assert "Paint" in bom.render(value, definition, notes)[0]
    value["lines"][0]["component_revision_id"] = "child-B"
    assert "Paint" not in bom.render(value, definition, notes)[0]
    assert list(notes.values())[0]["finish"] == "Paint <blue>"


def test_missing_and_estimated_masses_are_not_zero():
    column = {"field": "unit_mass", "unit": "g"}
    line = report()["lines"][0]
    assert bom.cell(line, column, {}, 3) == "~<0.001"
    line["unit_mass"] = None
    assert bom.cell(line, column, {}, 3) == "—"


def test_custom_title_is_escaped_and_optional_placeholders_follow_report():
    definition = {**bom.DEFAULT, "title": "Peças <A> & {item_number} / {revision_label}"}
    svg, _, height = bom.render(report(), definition, {})
    assert "Peças &lt;A&gt; &amp; A000001 / A" in svg
    assert "ENGINEERING BOM" not in svg
    updated = {**report(), "item_number": "A000002", "revision_label": "B"}
    assert "A000002 / B" in bom.render(updated, definition, {})[0]
    blank, _, blank_height = bom.render(report(), {**definition, "title": ""}, {})
    assert "Peças" not in blank and blank_height < height


def test_legacy_layout_keeps_default_title_without_changing_saved_definition():
    legacy = copy.deepcopy(bom.DEFAULT)
    del legacy["title"]
    assert bom.layout(legacy)["title"] == bom.DEFAULT["title"]
    assert "ENGINEERING BOM — A000001 Rev A" in bom.render(report(), legacy, {})[0]
    assert "title" not in legacy


@pytest.mark.parametrize(
    "change",
    [
        {"font": float("nan")},
        {"font": 0},
        {"columns": []},
        {"precision": 9},
        {"title": None},
        {"title": "x" * 301},
    ],
)
def test_invalid_layout_is_rejected(change):
    with pytest.raises(ValueError):
        bom.layout({**copy.deepcopy(bom.DEFAULT), **change})
