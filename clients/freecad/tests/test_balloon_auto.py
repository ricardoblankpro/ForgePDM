"""Automatic picking policy and observer boundaries without native CAD."""

from types import SimpleNamespace as NS

import pytest

from freecad.forgepdm import (
    balloon_auto as auto,
    balloon_geometry as geometry,
    drawing_balloons as links,
)


def test_unmapped_geometry_never_silently_selects_a_neighbour(monkeypatch):
    monkeypatch.setattr(geometry, "pick", lambda _: [(object(), "a"), (object(), None)])
    with pytest.raises(ValueError, match="without a pinned"):
        geometry.candidates(None, {})


def test_missing_entry_in_an_overlap_is_not_discarded(monkeypatch):
    monkeypatch.setattr(geometry, "pick", lambda _: [(object(), "a"), (object(), "missing")])
    monkeypatch.setattr(links, "entries", lambda _: [{"component_revision_id": "a"}])
    with pytest.raises(ValueError, match="absent"):
        geometry.candidates(None, {})


def test_split_entries_and_repeated_instances_remain_candidates(monkeypatch):
    obj1, obj2 = object(), object()
    monkeypatch.setattr(geometry, "pick", lambda _: [(obj1, "a"), (obj2, "a")])
    monkeypatch.setattr(
        links,
        "entries",
        lambda _: [
            {"component_revision_id": "a", "position": 5},
            {"component_revision_id": "a", "position": 6},
        ],
    )
    assert len(geometry.candidates(None, {})) == 4


def test_no_geometry_contact_has_no_nearest_part_fallback(monkeypatch):
    monkeypatch.setattr(geometry, "pick", lambda _: [])
    with pytest.raises(ValueError, match="does not touch"):
        geometry.candidates(None, {})


@pytest.fixture
def observer():
    observer = object.__new__(auto.Observer)
    observer.pending = set()
    observer.suspended = False
    observer.timer = NS(start=lambda: None)
    return observer


@pytest.mark.parametrize("event", ["OriginX", "OriginY", "SourceView"])
def test_arrow_events_queue_managed_balloons(observer, event):
    doc = NS(Name="root", Restoring=False, getObject=lambda _: object())
    obj = NS(Name="Balloon", Document=doc, TypeId="TechDraw::DrawViewBalloon")
    observer.slotChangedObject(obj, event)
    assert observer.pending == {("root", "Balloon")}


@pytest.mark.parametrize("event", ["X", "Y", "Text", "PDMBOMBinding"])
def test_bubble_and_internal_updates_do_not_requeue(observer, event):
    observer.slotChangedObject(NS(), event)
    assert not observer.pending


def test_restoring_and_unmanaged_documents_are_never_adopted(observer):
    doc = NS(Name="root", Restoring=True, getObject=lambda _: object())
    obj = NS(Name="Balloon", Document=doc, TypeId="TechDraw::DrawViewBalloon")
    observer.slotCreatedObject(obj)
    assert not observer.pending
    doc.Restoring = False
    doc.getObject = lambda _: None
    observer.slotCreatedObject(obj)
    assert not observer.pending


def test_undo_redo_discard_only_affected_document(observer):
    observer.pending = {("root", "Balloon"), ("other", "Balloon")}
    observer.slotUndoDocument(NS(Name="root"))
    assert observer.pending == {("other", "Balloon")}
    observer.slotRedoDocument(NS(Name="other"))
    assert not observer.pending


def test_attachment_change_is_detected_without_document_mutation(monkeypatch):
    saved = {"view": "View", "origin": [1, 2]}
    binding = {
        "format": 2,
        "component_revision_id": "a",
        "attachment": {"geometry": saved, "component": "Part"},
    }
    monkeypatch.setattr(geometry, "evidence", lambda _: {"view": "View", "origin": [2, 2]})
    with pytest.raises(ValueError, match="changed"):
        links.validate_attachment(object(), binding)
    assert binding["attachment"]["geometry"] == saved
