"""Fastener mass measurement is read-only and never estimates unknown materials."""

from types import SimpleNamespace

import pytest

from freecad.forgepdm import standard_mass


@pytest.fixture
def solid(monkeypatch):
    monkeypatch.setattr(
        standard_mass.fasteners, "extract", lambda obj: {"Type": "iso4016", "Diameter": "m8"}
    )
    monkeypatch.setattr(standard_mass.fasteners, "generator_version", lambda: "0.5.43")
    return SimpleNamespace(
        Thread=False,
        Shape=SimpleNamespace(
            Volume=1000,
            Solids=[1],
            isNull=lambda: False,
            isValid=lambda: True,
            exportBrepToString=lambda: "solid-brep",
        ),
    )


def current():
    return {
        "mass_kg": None,
        "token": "a" * 64,
        "estimate_context": {
            "geometry": {"Type": "iso4016", "Diameter": "m8"},
            "density_reference": {"density_kg_m3": "7800"},
        },
    }


def test_measurement_uses_only_selected_fastener_and_preserves_it(solid):
    before = vars(solid).copy()
    payload = standard_mass.estimate(solid, current())
    assert payload["volume_mm3"] == "1000" and payload["thread_mode"] == "simplified"
    assert (
        payload["geometry"] == current()["estimate_context"]["geometry"]
        and len(payload["shape_sha256"]) == 64
    )
    assert vars(solid) == before
    solid.Thread = True
    assert standard_mass.estimate(solid, current())["thread_mode"] == "modeled"


def test_known_mass_unknown_density_and_changed_geometry_are_not_replaced(solid):
    assert standard_mass.estimate(solid, {**current(), "mass_kg": "0.01"}) is None
    assert standard_mass.estimate(solid, {**current(), "estimate_context": None}) is None
    altered = current()
    altered["estimate_context"]["geometry"]["Diameter"] = "m10"
    assert standard_mass.estimate(solid, altered) is None


@pytest.mark.parametrize("volume", [0, -1, float("nan"), float("inf"), 1e20])
def test_invalid_volume_is_unavailable(solid, volume):
    solid.Shape.Volume = volume
    assert standard_mass.estimate(solid, current()) is None


def test_invalid_or_multiple_solids_are_unavailable(solid):
    solid.Shape.isValid = lambda: False
    assert standard_mass.estimate(solid, current()) is None
    solid.Shape.isValid = lambda: True
    solid.Shape.Solids = [1, 2]
    assert standard_mass.estimate(solid, current()) is None
