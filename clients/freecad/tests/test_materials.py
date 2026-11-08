"""Local undo and geometry guards without importing backend code."""

import importlib.util
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest


@pytest.fixture
def materials(addon_root):
    spec = importlib.util.spec_from_file_location(
        "local_materials", addon_root / "freecad/forgepdm/materials.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Shape:
    Volume = 1000000
    Solids = [1]

    def isNull(self):
        return False

    def isValid(self):
        return True

    def common(self, other):
        return SimpleNamespace(Volume=0)


class Document:
    def __init__(self):
        self.transactions = []

    def openTransaction(self, name):
        self.transactions.append("open")

    def commitTransaction(self):
        self.transactions.append("commit")

    def abortTransaction(self):
        self.transactions.append("abort")

    def recompute(self):
        pass


class Metadata:
    def addProperty(self, kind, name, group):
        setattr(self, name, "")


def test_multiple_material_mass_and_undo_boundary(materials):
    doc = Document()
    metadata = Metadata()
    first = SimpleNamespace(Name="First", Document=doc, Shape=Shape())
    second = SimpleNamespace(Name="Second", Document=doc, Shape=Shape())
    result = materials.assign(
        doc,
        metadata,
        "parent",
        {"token": "before"},
        [],
        [(first, "steel", "7850"), (second, "aluminium", "2700")],
    )
    assert Decimal(metadata.PDMFinishedMassKg) == Decimal("10.55")
    assert len(result["mass_evidence"]) == 2
    assert json.loads(metadata.PDMMaterialInputs)["expected_token"] == "before"
    assert doc.transactions == ["open", "commit"]


def test_duplicate_or_overlapping_geometry_does_not_mutate(materials):
    doc = Document()
    metadata = Metadata()
    first = SimpleNamespace(Name="First", Document=doc, Shape=Shape())
    with pytest.raises(ValueError, match="distinct"):
        materials.assign(
            doc,
            metadata,
            "parent",
            {"token": "before"},
            [],
            [(first, "steel", "7850"), (first, "steel", "7850")],
        )
    assert not doc.transactions
    assert not hasattr(metadata, "PDMMaterialInputs")


def test_cancelled_transaction_rolls_back(materials):
    doc = Document()
    doc.recompute = lambda: (_ for _ in ()).throw(RuntimeError("recompute failed"))
    with pytest.raises(RuntimeError):
        materials.assign(doc, Metadata(), "parent", {"token": "before"}, [], [])
    assert doc.transactions == ["open", "abort"]
