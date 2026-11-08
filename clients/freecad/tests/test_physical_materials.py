"""CAD-independent mass arithmetic and native assignment guards with small fake solids."""

import importlib.util
from decimal import Decimal
from types import SimpleNamespace
import pytest


@pytest.fixture
def physical(addon_root, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "local_physical", addon_root / "freecad/forgepdm/physical_materials.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(
        module,
        "ensure_native",
        lambda binding: SimpleNamespace(
            UUID=module.native_uuid(binding), density=binding["density_kg_m3"]
        ),
    )
    monkeypatch.setattr(module, "density", lambda material: material.density)
    return module


BINDING = {
    "version": 1,
    "source_uuid": "06ae5c92-de7b-46c9-984d-4dd87964bc5c",
    "name": "Steel-C15",
    "density_kg_m3": "7800",
    "author": "",
    "license": "",
}


class Metadata:
    RevisionId = "part"

    def addProperty(self, kind, name, group):
        setattr(self, name, "")

    def setEditorMode(self, *args):
        pass


class Shape:
    Volume = 1000000
    Solids = [1]

    def isNull(self):
        return False

    def isValid(self):
        return True

    def common(self, other):
        return SimpleNamespace(Volume=0)


class Solid:
    TypeId = "PartDesign::Body"

    def __init__(self, name):
        self.Name = name
        self.InListRecursive = []
        self.Shape = Shape()
        self.ShapeMaterial = None

    def isDerivedFrom(self, kind):
        return kind == "Part::Feature"


class Document:
    def __init__(self, objects):
        self.Objects = objects

    def getObject(self, name):
        return next((o for o in self.Objects if o.Name == name), None)


def test_mass_counts_final_bodies_once_and_recalculates(physical):
    body = Solid("Body")
    feature = Solid("Pad")
    feature.TypeId = "PartDesign::Pad"
    feature.InListRecursive = [body]
    document = Document([body, feature])
    metadata = Metadata()
    value = physical.apply(document, metadata, BINDING)
    assert len(value["objects"]) == 1 and Decimal(value["mass_kg"]) == Decimal("7.8")
    body.Shape = Shape()
    body.Shape.Volume = 2000000
    value = physical.refresh(document, metadata)
    assert Decimal(value["mass_kg"]) == Decimal("15.6")


def test_material_mismatch_blocks_publication_refresh(physical):
    body = Solid("Body")
    doc = Document([body])
    metadata = Metadata()
    physical.apply(doc, metadata, BINDING)
    body.ShapeMaterial = SimpleNamespace(UUID=physical.native_uuid(BINDING), density="7850")
    with pytest.raises(ValueError, match="Native material changed"):
        physical.refresh(doc, metadata)
    body.ShapeMaterial = SimpleNamespace(UUID="wrong")
    with pytest.raises(ValueError, match="Native material changed"):
        physical.refresh(doc, metadata)


def test_unavailable_and_overlapping_geometry_never_report_zero(physical):
    metadata = Metadata()
    value = physical.apply(Document([]), metadata, BINDING)
    assert value["mass_kg"] is None and value["reason"] == "No final solid geometry"
    first = Solid("First")
    second = Solid("Second")
    second.Shape = Shape()
    second.Shape.common = lambda other: SimpleNamespace(Volume=10)
    value = physical.apply(Document([first, second]), metadata, BINDING)
    assert value["mass_kg"] is None and "overlap" in value["reason"]
    assert metadata.PDMPartMassKg == ""


def test_cache_card_is_deterministic_and_has_no_inheritance(physical):
    text = physical.card(BINDING)
    assert physical.native_uuid(BINDING) in text
    assert "7800 kg/m^3" in text and "Inherits" not in text
    assert "Density:" not in physical.card(physical.unassigned_binding())
