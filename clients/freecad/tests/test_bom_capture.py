"""Mocked document adapter tests; real FreeCAD evidence is separate."""

from types import SimpleNamespace as NS

import pytest

from freecad.forgepdm import cad
from freecad.forgepdm.workspace import WorkspaceError


@pytest.fixture(autouse=True)
def modification_adapter(monkeypatch):
    monkeypatch.setattr(cad, "document_modified", lambda document: document.isTouched())


def documents():
    child = NS(
        FileName="/tmp/child.FCStd",
        isTouched=lambda: False,
        getObject=lambda name: NS(ItemId="item", RevisionId="revision"),
    )
    root = NS(Objects=[])
    target = NS(TypeId="Part::Feature", Name="Box", Document=child)
    first = NS(TypeId="App::Link", Name="First", Document=root, LinkedObject=target)
    second = NS(TypeId="App::Link", Name="Second", Document=root, LinkedObject=first)
    root.Objects = [NS(TypeId="App::Part", Name="Group"), first, second]
    return root, child, first, second


def test_internal_repeated_link_resolves_to_same_exact_external_component():
    root, child, first, second = documents()
    references = cad.capture_bom(root)
    assert [ref["object_name"] for ref in references] == ["First", "Second"]
    assert {ref["target_object_name"] for ref in references} == {"Box"}
    assert {ref["target_revision_id"] for ref in references} == {"revision"}
    # A child document's assembly links are never traversed.
    child.Objects = [NS(TypeId="App::Link", LinkedObject=None)]
    assert cad.capture_bom(root) == references


@pytest.mark.parametrize(
    "fault", ["array", "cycle", "missing", "subelement", "local", "dirty", "proxy"]
)
def test_ambiguous_or_unpinned_structures_are_rejected(fault):
    root, child, first, second = documents()
    if fault == "array":
        first.ElementCount = 3
    elif fault == "cycle":
        first.LinkedObject = second
    elif fault == "missing":
        first.LinkedObject = None
    elif fault == "subelement":
        first.LinkedObject = (first.LinkedObject, ["Face1"])
    elif fault == "local":
        first.LinkedObject.Document = root
    elif fault == "dirty":
        child.isTouched = lambda: True
    else:
        root.Objects[0].Proxy = object()
    with pytest.raises(WorkspaceError):
        cad.capture_bom(root)
