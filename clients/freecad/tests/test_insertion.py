"""Rigid representation membership, integrity and cycle policy."""

import json
from types import SimpleNamespace as NS

import pytest

from freecad.forgepdm import insertion
from freecad.forgepdm.workspace import WorkspaceError


def fixture(monkeypatch):
    root = NS(Name="Assembly", TypeId="Assembly::AssemblyObject", Group=[])
    extra = NS(Name="Screw", TypeId="Part::FeaturePython", Shape=NS(isNull=lambda: False))
    doc = NS(Objects=[root, extra])
    root.Document = doc
    extra.Document = doc
    monkeypatch.setattr(insertion.fasteners, "objects", lambda d: [extra])
    monkeypatch.setattr(insertion.fasteners, "recognized", lambda o: o is extra)
    return doc, root, extra


def test_external_fasteners_included_without_moving_them(monkeypatch):
    doc, root, extra = fixture(monkeypatch)
    assert insertion.source_members(doc) == [root, extra]
    assert root.Group == []


def test_contained_fasteners_are_not_duplicated(monkeypatch):
    doc, root, extra = fixture(monkeypatch)
    root.Group = [extra]
    assert insertion.source_members(doc) == [root]


def test_missing_fasteners_runtime_fails_instead_of_omitting_geometry(monkeypatch):
    doc, root, extra = fixture(monkeypatch)
    monkeypatch.setattr(insertion.fasteners, "recognized", lambda o: False)
    with pytest.raises(WorkspaceError):
        insertion.source_members(doc)


@pytest.mark.parametrize("count", [0, 2])
def test_ambiguous_or_missing_assembly_rejected(count):
    with pytest.raises(WorkspaceError):
        insertion.assembly(NS(Objects=[NS(TypeId="Assembly::AssemblyObject")] * count))


def test_recursive_membership_does_not_duplicate_external_fasteners(monkeypatch):
    doc, root, extra = fixture(monkeypatch)
    root.Group = [NS(Name="Group", Document=doc, Group=[extra])]
    assert insertion.source_members(doc) == [root]


def test_representation_resolves_original_and_detects_damage(monkeypatch):
    doc, root, extra = fixture(monkeypatch)
    links = [
        NS(Name=str(i), TypeId="App::Link", LinkedObject=o) for i, o in enumerate([root, extra])
    ]
    group = NS(
        TypeId="App::Part",
        Group=links,
        ForgePDMRepresentation=json.dumps({"version": 1, "members": ["0", "1"]}),
    )
    occurrence = NS(LinkedObject=group)
    assert insertion.source(occurrence) is root
    group.Group = links[:1]
    with pytest.raises(WorkspaceError):
        insertion.source(occurrence)


@pytest.mark.parametrize("value", ["{}", "null", '{"version": 99}', "broken"])
def test_invalid_representation_fails_closed(value):
    obj = NS(LinkedObject=NS(TypeId="App::Part", ForgePDMRepresentation=value))
    with pytest.raises(WorkspaceError):
        insertion.source(obj)


def test_transitive_self_insertion_rejected():
    def doc(name, item):
        return NS(Name=name, Objects=[], getObject=lambda _: NS(ItemId=item))

    parent, sub, nested = doc("Parent", "A1"), doc("Sub", "A2"), doc("Nested", "A1")
    sub.Objects.append(NS(TypeId="App::Link", LinkedObject=NS(Document=nested)))
    with pytest.raises(WorkspaceError):
        insertion.check_cycle(parent, sub)


def test_unrelated_dependency_is_allowed():
    parent = NS(getObject=lambda _: NS(ItemId="A1"))
    source = NS(Name="Source", Objects=[], getObject=lambda _: NS(ItemId="A2"))
    insertion.check_cycle(parent, source)


def test_part_body_referenced_by_a_drawing_is_still_an_insertion_target():
    body = NS(Name="Body", TypeId="PartDesign::Body", Group=[], Shape=NS(isNull=lambda: False))
    drawing = NS(Name="View", TypeId="TechDraw::DrawViewPart", isDerivedFrom=lambda _: False)
    document = NS(Objects=[body, drawing], RootObjects=[drawing])
    assert insertion.part_targets(document) == [body]
