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


def test_report_view_keys_isolate_notes_and_preserve_flat_notes_after_renumbering():
    value = report()
    direct = {**value["lines"][0], "row_key": "child-A:5"}
    nested = {**direct, "row_key": "indented:root/sub/5", "position": "2.5", "level": 2}
    flat = {**direct, "row_key": "flattened:child-A", "position": 1, "quantity": "12"}
    bundle = {
        **{k: v for k, v in value.items() if k != "lines"},
        "views": {"direct": [direct], "indented": [nested], "flattened": [flat]},
    }
    column = {
        "field": "custom",
        "heading": "Finish",
        "width": 30,
        "align": "left",
        "unit": "kg",
        "key": "finish",
    }
    notes = {
        bom.row_key(direct): {"finish": "Direct note"},
        bom.row_key(flat): {"finish": "Flat note"},
    }
    for view, expected in [("direct", "Direct note"), ("indented", ""), ("flattened", "Flat note")]:
        selected = bom.report_for_view(bundle, view)
        assert bom.cell(selected["lines"][0], column, notes, 3) == expected
        definition = {**bom.DEFAULT, "view": view}
        svg, _, _ = bom.render(selected, definition, notes)
        assert (">2.5<" in svg) == (view == "indented")
    flat["position"] = 9
    assert bom.cell(flat, column, notes, 3) == "Flat note"
    assert bom.layout({k: v for k, v in bom.DEFAULT.items() if k != "view"})["view"] == "direct"


def test_flat_drawing_rejects_unresolved_structure_and_view_mismatch():
    value = {**report(), "view": "flattened", "structure_complete": False}
    with pytest.raises(ValueError, match="incomplete"):
        bom.render(value, {**bom.DEFAULT, "view": "flattened"}, {})
    with pytest.raises(ValueError, match="do not match"):
        bom.render(value, bom.DEFAULT, {})


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_saved_drawing_language_is_frozen_and_legacy_formats_remain_readable(version):
    import json
    from types import SimpleNamespace

    value = report()
    if version >= 3:
        value.update(language="pt-BR", token="frozen")
        value["lines"][0].update(
            description="Chapa de aço",
            localization={"description": {"translation_id": "approved-id", "source_version": 2}},
        )
    obj = SimpleNamespace(
        PDMTableData=json.dumps(
            {"format": version, "layout": bom.DEFAULT, "report": value, "notes": {}}
        )
    )
    before = obj.PDMTableData
    restored = bom.read_table(obj)
    svg, _, _ = bom.render(restored["report"], restored["layout"], restored["notes"])
    assert obj.PDMTableData == before
    if version >= 3:
        assert restored["report"]["language"] == "pt-BR" and "Chapa de aço" in svg
        assert (
            restored["report"]["lines"][0]["localization"]["description"]["translation_id"]
            == "approved-id"
        )


def sorting_report(view="direct"):
    rows = [
        dict(
            component_revision_id="p10",
            position=1,
            item_number="P10",
            quantity="10",
            unit_mass=None,
            total_mass=None,
            description="Zinc",
            revision_label="A",
        ),
        dict(
            component_revision_id="p2",
            position=10,
            item_number="P2",
            quantity="2",
            unit_mass="0.1",
            total_mass="0.2",
            description="Água",
            revision_label="A",
        ),
        dict(
            component_revision_id="p1",
            position=2,
            item_number="P1",
            quantity="1.5",
            unit_mass="0.02",
            total_mass="0.03",
            description="Aço",
            revision_label="A",
        ),
    ]
    return dict(
        item_number="A000001",
        revision_label="A",
        view=view,
        lines=rows,
        token="unchanged",
        language="pt-BR",
    )


@pytest.mark.parametrize("view", ["direct", "flattened"])
def test_item_number_default_is_natural_stable_and_does_not_mutate_report(view):
    value = sorting_report(view)
    before = copy.deepcopy(value)
    definition = bom.layout({**bom.DEFAULT, "view": view})
    assert definition["sort_by"] == "item_number"
    lines = bom.ordered_lines(value, definition)
    assert [line["item_number"] for line in lines] == ["P1", "P2", "P10"]
    assert [line["position"] for line in lines] == [2, 10, 1]
    svg, _, _ = bom.render(value, definition, {})
    assert svg.index(">P1<") < svg.index(">P2<") < svg.index(">P10<")
    assert value == before


@pytest.mark.parametrize(
    ("field", "order", "expected"),
    [
        ("position", "ascending", ["P10", "P1", "P2"]),
        ("position", "descending", ["P2", "P1", "P10"]),
        ("description", "ascending", ["P1", "P2", "P10"]),
        ("quantity", "ascending", ["P1", "P2", "P10"]),
        ("quantity", "descending", ["P10", "P2", "P1"]),
        ("unit_mass", "ascending", ["P1", "P2", "P10"]),
        ("unit_mass", "descending", ["P2", "P1", "P10"]),
        ("total_mass", "ascending", ["P1", "P2", "P10"]),
        ("total_mass", "descending", ["P2", "P1", "P10"]),
        ("bom_order", "ascending", ["P10", "P2", "P1"]),
    ],
)
def test_sort_values_numbers_localized_text_and_missing_mass(field, order, expected):
    value = sorting_report()
    definition = bom.layout({**bom.DEFAULT, "sort_by": field, "sort_order": order})
    assert [line["item_number"] for line in bom.ordered_lines(value, definition)] == expected


def test_sort_ties_keep_bom_order_and_standard_description_uses_display_fallback():
    value = sorting_report()
    value["lines"][0].update(item_number="S10", description="", item_name="Água", quantity="2")
    definition = {**bom.DEFAULT, "sort_by": "description"}
    assert [line["item_number"] for line in bom.ordered_lines(value, definition)] == [
        "P1",
        "S10",
        "P2",
    ]
    definition = {**bom.DEFAULT, "sort_by": "quantity", "sort_order": "descending"}
    assert [line["item_number"] for line in bom.ordered_lines(value, definition)] == [
        "S10",
        "P2",
        "P1",
    ]


def test_indented_sort_keeps_occurrence_subtrees_and_position_paths_together():
    value = sorting_report("indented")
    value["lines"] = [
        dict(
            component_revision_id=key,
            row_key=key,
            item_number=number,
            level=level,
            position=position,
        )
        for key, number, level, position in [
            ("b", "A20", 1, "1"),
            ("b-p10", "P10", 2, "1.1"),
            ("b-p2", "P2", 2, "1.10"),
            ("a", "A10", 1, "2"),
            ("a-sub", "A30", 2, "2.1"),
            ("a-leaf", "P3", 3, "2.1.1"),
            ("a-p2", "P2", 2, "2.10"),
        ]
    ]
    before = copy.deepcopy(value)
    definition = {**bom.DEFAULT, "view": "indented"}
    lines = bom.ordered_lines(value, definition)
    assert [line["row_key"] for line in lines] == [
        "a",
        "a-sub",
        "a-leaf",
        "a-p2",
        "b",
        "b-p2",
        "b-p10",
    ]
    reverse = bom.ordered_lines(value, {**definition, "sort_order": "descending"})
    assert [line["row_key"] for line in reverse] == [
        "b",
        "b-p10",
        "b-p2",
        "a",
        "a-p2",
        "a-sub",
        "a-leaf",
    ]
    assert value == before


def test_sorting_keeps_custom_notes_on_their_original_row_identities():
    value = sorting_report()
    definition = bom.layout(bom.DEFAULT)
    definition["columns"] = [
        dict(field="item_number", heading="Item", width=30, align="left"),
        dict(field="custom", heading="Note", width=30, align="left", key="note"),
    ]
    notes = {
        bom.row_key(line): {"note": "Note for " + line["item_number"]} for line in value["lines"]
    }
    svg, _, _ = bom.render(value, definition, notes)
    texts = [node.text for node in ET.fromstring(svg).iter() if node.tag.endswith("text")]
    assert texts[-6:] == ["P1", "Note for P1", "P2", "Note for P2", "P10", "Note for P10"]


@pytest.mark.parametrize("version", [1, 2, 3])
def test_legacy_table_layout_without_sort_fields_keeps_stored_order(version):
    import json
    from types import SimpleNamespace

    definition = copy.deepcopy(bom.DEFAULT)
    del definition["sort_by"], definition["sort_order"]
    value = sorting_report()
    obj = SimpleNamespace(
        PDMTableData=json.dumps(dict(format=version, layout=definition, report=value, notes={}))
    )
    before = obj.PDMTableData
    saved = bom.read_table(obj)
    normalized = bom.layout(saved["layout"])
    assert normalized["sort_by"] == "bom_order"
    assert bom.ordered_lines(saved["report"], normalized) == value["lines"]
    assert obj.PDMTableData == before


@pytest.mark.parametrize(
    "change", [{"sort_by": "unknown"}, {"sort_by": []}, {"sort_order": "unknown"}]
)
def test_invalid_sorting_is_rejected(change):
    with pytest.raises(ValueError, match="sort"):
        bom.layout({**bom.DEFAULT, **change})


def test_sorted_format_requires_an_explicit_sort_policy():
    import json
    from types import SimpleNamespace

    definition = copy.deepcopy(bom.DEFAULT)
    del definition["sort_by"]
    obj = SimpleNamespace(
        PDMTableData=json.dumps(
            dict(format=4, layout=definition, report=sorting_report(), notes={})
        )
    )
    with pytest.raises(ValueError, match="sorting"):
        bom.read_table(obj)
