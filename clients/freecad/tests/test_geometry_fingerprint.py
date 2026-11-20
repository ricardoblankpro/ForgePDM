"""Persistence noise is ignored; topology, geometry and locations remain evidence."""

import pytest

from freecad.forgepdm.geometry_fingerprint import canonical_brep, fingerprint


def brep(point="1 2 3", flags="0101000", reference="+1 0", version=1):
    owner = "Open Cascade" if version == 3 else "Matra-Datavision"
    return f"CASCADE Topology V{version}, (c) {owner}\nLocations 0\nTShapes 1\nVe\n1e-07\n{point}\n0 0\n{flags}\n*\n{reference}\n"


@pytest.mark.parametrize("flags", ["0001000", "1111000", "0011000", "1001000"])
def test_processing_flags_and_tiny_numeric_roundoff_are_not_geometry_changes(flags):
    assert fingerprint(brep("-0 1.0000000000000002 7.888609e-31", flags)) == fingerprint(
        brep("0 1 0")
    )


@pytest.mark.parametrize(
    "change",
    [
        dict(point="1.00000001 2 3"),
        dict(point="1 2 4"),
        dict(flags="0101100"),
        dict(flags="0100000"),
        dict(flags="0101010"),
        dict(flags="0101001"),
        dict(reference="-1 0"),
        dict(reference="+1 1"),
    ],
)
def test_real_values_geometric_flags_orientation_and_location_references_change_hash(change):
    assert fingerprint(brep(**change)) != fingerprint(brep())


def test_numeric_normalization_keeps_topology_integer_words_and_large_integers_exact():
    text = brep("1000000000000001 2.0 3e0")
    assert "1000000000000001" in canonical_brep(text)
    assert fingerprint(text) == fingerprint(brep("1000000000000001 2 3"))
    assert fingerprint(text) != fingerprint(brep("1000000000000002 2 3"))


@pytest.mark.parametrize("version", [1, 2, 3])
def test_only_known_occt_versions_are_supported(version):
    assert len(fingerprint(brep(version=version))) == 64


@pytest.mark.parametrize(
    "text",
    [
        "",
        "arbitrary text",
        brep(version=4),
        brep().replace("TShapes 1", "TShapes 2"),
        brep().replace("0101000", "01010000"),
        brep().replace("Ve\n", "Unknown\n"),
        brep("NaN 2 3"),
        brep("1e999 2 3"),
    ],
)
def test_unknown_or_malformed_evidence_fails_closed(text):
    with pytest.raises(ValueError):
        fingerprint(text)
