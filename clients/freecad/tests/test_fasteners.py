"""Optional adapter tests without importing FreeCAD or vendor source."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from freecad.forgepdm import bom, fasteners
from freecad.forgepdm.workspace import WorkspaceError


class FSScrewObject:
    pass


FSScrewObject.__module__ = "FastenersCmd"


class Object(SimpleNamespace):
    def addProperty(self, *args):
        pass


def bolt(name="Bolt", standard="ISO4017", length="25"):
    return Object(
        Name=name,
        TypeId="Part::FeaturePython",
        Proxy=FSScrewObject(),
        Type=standard,
        Diameter="M8",
        Length=length,
        LengthCustom=SimpleNamespace(Value=25),
        LeftHanded=False,
        Thread=False,
        Offset=0,
    )


def test_association_invalidated_by_size_but_not_placement_or_display():
    obj = bolt()
    fasteners.associate(obj, str(uuid4()))
    assert fasteners.association(obj)
    obj.Thread = True
    obj.Offset = 10
    assert fasteners.association(obj)
    obj.Length = "30"
    assert fasteners.association(obj) is None


def test_duplicate_occurrences_and_missing_workbench_are_rejected():
    first, second = bolt(), bolt("Copy")
    fasteners.associate(first, str(uuid4()))
    second.PDMStandardAssociation = first.PDMStandardAssociation
    with pytest.raises(WorkspaceError, match="Copied"):
        fasteners.capture(SimpleNamespace(Objects=[first, second]))
    second.Proxy = None
    with pytest.raises(WorkspaceError):
        fasteners.extract(second)


@pytest.mark.parametrize("standard", ["ISO4017", "ISO4032", "ISO7089", "ISO4762"])
def test_family_independent_extraction(standard):
    assert fasteners.extract(bolt(standard=standard))["Type"] == standard.lower()


def test_embedded_and_linked_occurrences_group_by_exact_revision():
    revision = str(uuid4())
    refs = [
        dict(
            object_name="Bolt" + str(i),
            property_name="PDMStandardAssociation",
            target_revision_id=revision,
        )
        for i in range(8)
    ]
    selected = [(r["object_name"], r["property_name"]) for r in refs]
    lines = bom.propose_lines({"profile": "freecad-app-link-v1", "references": refs}, selected)
    assert len(lines) == 1 and lines[0].quantity == 8
    assert lines[0].component_revision_id == revision


def test_null_attachment_shape_is_rejected():
    obj = bolt()
    target = SimpleNamespace(getSubObject=lambda _: SimpleNamespace(isNull=lambda: True))
    obj.BaseObject = (target, ["Edge999"])
    with pytest.raises(WorkspaceError, match="cannot be resolved"):
        fasteners.attachment(obj)


def test_malformed_association_requires_review():
    obj = bolt()
    obj.PDMStandardAssociation = "[]"
    assert fasteners.association(obj) is None


def test_projected_subassembly_links_do_not_become_embedded_occurrences():
    projected = SimpleNamespace(TypeId="App::Link", PDMStandardAssociation="inherited")
    assert fasteners.objects(SimpleNamespace(Objects=[projected])) == []


@pytest.mark.parametrize("path", ["Body002.Hole.Edge5", "Component.Face2", "Edge5"])
def test_local_qualified_attachment_paths(path):
    obj = bolt()
    obj.Document = object()
    target = SimpleNamespace(
        Document=obj.Document, getSubObject=lambda _: SimpleNamespace(isNull=lambda: False)
    )
    obj.BaseObject = (target, [path])
    assert fasteners.attachment(obj) == (target, path)


@pytest.mark.parametrize(
    "path", ["../Edge5", "Body..Edge5", "Body/Edge5", "Body.Edge0", "Body.#Edge5"]
)
def test_malformed_local_attachment_paths_remain_rejected(path):
    obj = bolt()
    obj.Document = object()
    target = SimpleNamespace(Document=obj.Document)
    obj.BaseObject = (target, [path])
    with pytest.raises(WorkspaceError):
        fasteners.attachment(obj)


def test_external_qualified_attachment_needs_a_manifest_adapter():
    obj = bolt()
    obj.Document = object()
    obj.BaseObject = (SimpleNamespace(Document=object()), ["Body.Hole.Edge5"])
    with pytest.raises(WorkspaceError):
        fasteners.attachment(obj)
