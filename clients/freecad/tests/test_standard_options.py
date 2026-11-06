"""Controlled options and purchasing names are deterministic and geometry-specific."""

import pytest

from freecad.forgepdm import standard_options as options


def geom(norm="ISO4016", diameter="M12", length="70"):
    value = {"Type": norm, "Diameter": diameter}
    if length is not None:
        value["Length"] = length
    return value


@pytest.mark.parametrize(
    "norm,kind,family,grade,dimension",
    [
        ("ISO4016", "SCREW", "HEX HEAD", "8.8", "M12X70"),
        ("ISO4032", "NUT", "HEX", "8", "M12"),
        ("ISO7089", "WASHER", "FLAT", "200HV", "M12"),
    ],
)
def test_generated_name_matches_user_template(norm, kind, family, grade, dimension):
    geometry = geom(norm, length="70" if kind == "SCREW" else None)
    spec = dict(geometry=geometry, material="carbon steel", grade=grade, finish="zinc plated")
    name, description = options.catalog_text(spec, kind, family)
    assert name == f"{kind} CARBON STEEL {family} {norm} {dimension} {grade} ZINC PLATED"
    assert description == name and name.isupper()


def test_custom_length_pitch_and_left_hand_are_not_lost():
    geometry = dict(geom(), Length="Custom", LengthCustom="85", PitchCustom="1.5", LeftHanded=True)
    spec = dict(geometry=geometry, material="steel", grade="8.8", finish="plain")
    name, _ = options.catalog_text(spec, "SCREW", "HEX HEAD")
    assert "M12X1.5X85 LH" in name


def test_unknowns_are_explicit_and_plain_is_not_unknown():
    base = dict(geometry=geom(), material=None, grade=None, finish=None)
    name, _ = options.catalog_text(base, "SCREW", "HEX HEAD")
    assert "MATERIAL UNKNOWN" in name and "GRADE UNKNOWN" in name and "FINISH UNKNOWN" in name
    assert options.catalog_text(dict(base, finish="plain"), "SCREW", "HEX HEAD")[0].endswith(
        "PLAIN"
    )


def test_classification_uses_standard_not_translated_label():
    assert options.classification(geom("iso4016")) == ("SCREW", "HEX HEAD")
    assert options.classification(geom("DIN934")) == ("NUT", "HEX")
    assert options.classification(geom("UNKNOWN")) is None


def test_stainless_cannot_select_steel_strength_class():
    codes = options.grades("a2", "SCREW", "HEX HEAD", geom())
    assert {o["value"] for o in codes} == {None, "a2-50", "a2-70", "a2-80"}
    with pytest.raises(ValueError):
        options.selected_spec(geom(), "a2", "ISO 898-1:8.8", "plain", "SCREW", "HEX HEAD")


def test_nut_and_set_screw_and_washer_classes_are_distinct():
    assert {o["value"] for o in options.grades("steel", "NUT", "HEX", geom("ISO4032"))} == {
        None,
        "5",
        "6",
        "8",
        "10",
        "12",
    }
    assert {o["value"] for o in options.grades("steel", "NUT", "HEX THIN", geom("ISO4035"))} == {
        None,
        "04",
        "05",
    }
    assert "45h" in {o["value"] for o in options.grades("steel", "SCREW", "SET", geom("ISO4026"))}
    assert "200hv" in {
        o["value"] for o in options.grades("steel", "WASHER", "FLAT", geom("ISO7089"))
    }


def test_diameter_limits_hide_9_8_for_large_metric_bolts():
    assert "9.8" not in {
        o["value"] for o in options.grades("steel", "SCREW", "HEX HEAD", geom(diameter="M20"))
    }


def test_extended_options_are_explicit_and_namespace_sae_classes():
    assert not any(
        o["value"] == "sae j429 grade 5"
        for o in options.grades("steel", "SCREW", "HEX HEAD", geom())
    )
    assert any(
        o["value"] == "sae j429 grade 5"
        for o in options.grades("steel", "SCREW", "HEX HEAD", geom(), True)
    )
    assert "cadmium" not in {o["id"] for o in options.finishes("steel")}
    assert "cadmium" in {o["id"] for o in options.finishes("steel", True)}


def test_polymer_does_not_offer_metal_plating_or_steel_class():
    assert {o["id"] for o in options.finishes("polymer-pa6")} == {"unknown", "plain"}
    assert {o["id"] for o in options.grades("polymer-pa6", "SCREW", "HEX HEAD", geom())} == {
        "unknown",
        "not-applicable",
    }


def test_options_have_unique_stable_ids_and_large_names_fail_explicitly():
    for rows in (options.MATERIALS, options.FINISHES):
        assert len({o["id"] for o in rows}) == len(rows)
    with pytest.raises(ValueError, match="200-character"):
        options.catalog_text(
            dict(geometry=geom(), material="x" * 190, grade="8.8", finish="plain"),
            "SCREW",
            "HEX HEAD",
        )


def test_spring_washers_do_not_offer_flat_washer_classes():
    assert {o["id"] for o in options.grades("steel", "WASHER", "SPRING", geom("DIN127"))} == {
        "unknown"
    }


def test_iso4036_uses_its_specific_hardness_system():
    values = {o["value"] for o in options.grades("steel", "NUT", "HEX THIN", geom("ISO4036"))}
    assert values == {None, "din 267-24 14h"}
