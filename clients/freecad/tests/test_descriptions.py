"""Simple local metadata is undoable and preserves pending descriptions."""

import importlib.util
import json
from types import SimpleNamespace

import pytest


@pytest.fixture
def descriptions(addon_root):
    spec = importlib.util.spec_from_file_location(
        "test_local_descriptions", addon_root / "freecad/forgepdm/descriptions.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Document:
    def __init__(self):
        self.events = []
        self.metadata = SimpleNamespace(RevisionId="revision", PDMMaterialInputs="legacy")
        self.metadata.addProperty = lambda kind, name, group: setattr(self.metadata, name, "")

    def getObject(self, name):
        return self.metadata

    def openTransaction(self, name):
        self.events.append("open")

    def commitTransaction(self):
        self.events.append("commit")

    def abortTransaction(self):
        self.events.append("abort")

    def recompute(self):
        pass


def test_part_selection_and_clear_legacy_proposal(descriptions):
    doc = Document()
    descriptions.apply(
        doc, doc.metadata, {"token": "before"}, "STEEL PLATE 6 MM", "material-revision"
    )
    assert doc.metadata.PDMDescription == "STEEL PLATE 6 MM"
    assert not doc.metadata.PDMMaterialInputs
    assert descriptions.local(doc)["material_revision_id"] == "material-revision"
    assert doc.events == ["open", "commit"]


def test_pending_local_edit_survives_upload_preparation(descriptions):
    doc = Document()
    descriptions.apply(doc, doc.metadata, {"token": "before"}, "General mounting")
    descriptions.prepare(
        doc,
        doc.metadata,
        {"token": "server", "description": "Web edit", "material_revision_id": None},
    )
    assert descriptions.local(doc)["description"] == "General mounting"
    assert descriptions.local(doc)["expected_token"] == "before"


def test_new_revision_adopts_copied_server_description(descriptions):
    doc = Document()
    descriptions.apply(doc, doc.metadata, {"token": "before"}, "Original")
    doc.metadata.RevisionId = "revision-b"
    descriptions.prepare(
        doc, doc.metadata, {"token": "new", "description": "Original", "material_revision_id": None}
    )
    assert json.loads(doc.metadata.PDMDescriptionData)["revision_id"] == "revision-b"


def test_failure_aborts_local_transaction(descriptions):
    doc = Document()

    def fail():
        raise RuntimeError("recompute")

    doc.recompute = fail
    with pytest.raises(RuntimeError):
        descriptions.apply(doc, doc.metadata, {"token": "before"}, "Text")
    assert doc.events == ["open", "abort"]


def test_legacy_description_adopts_new_server_physical_link(descriptions, monkeypatch):
    doc = Document()
    legacy = {
        "version": 1,
        "revision_id": "revision",
        "description": "PLATE",
        "material_revision_id": "material",
        "expected_token": "old",
    }
    doc.metadata.PDMDescriptionData = json.dumps(legacy)
    binding = {"name": "Steel", "density_kg_m3": "7800"}
    current = {
        "description": "PLATE",
        "material_revision_id": "material",
        "physical_material": binding,
        "token": "new",
    }
    applied = []
    monkeypatch.setattr(descriptions, "apply", lambda *args: applied.append(args))
    descriptions.prepare(doc, doc.metadata, current)
    assert len(applied) == 1
    assert applied[0][2] is current and applied[0][-1] == binding
    legacy["material_revision_id"] = "pending-other-material"
    doc.metadata.PDMDescriptionData = json.dumps(legacy)
    descriptions.prepare(doc, doc.metadata, current)
    assert len(applied) == 1
    assert descriptions.local(doc)["expected_token"] == "old"


def test_matching_v2_without_mass_metadata_is_rebuilt(descriptions, monkeypatch):
    doc = Document()
    doc.metadata.ItemNumber = "P000001"
    value = {
        "version": 2,
        "revision_id": "revision",
        "description": "PLATE",
        "material_revision_id": "material",
        "physical_material": {"name": "Steel"},
        "expected_token": "old",
    }
    doc.metadata.PDMDescriptionData = json.dumps(value)
    current = {**value, "token": "new"}
    applied = []
    monkeypatch.setattr(descriptions, "apply", lambda *args: applied.append(args))
    descriptions.prepare(doc, doc.metadata, current)
    assert len(applied) == 1 and applied[0][-1] == value["physical_material"]
