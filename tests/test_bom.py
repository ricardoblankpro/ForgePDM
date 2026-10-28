from decimal import Decimal

import pytest

from forgepdm.domain.entities import Conflict, LifecycleState

from conftest import create_item


def _release(backend, revision_id):
    backend.revisions.check_in(backend.users["editor"], revision_id, "Ready for release")
    backend.revisions.transition_lifecycle(
        backend.users["editor"], revision_id, LifecycleState.RELEASED
    )


def test_bom_uses_explicit_revisions_and_assembly_release_checks_components(backend):
    component = create_item(backend, name="Bracket")
    _release(backend, component.current_revision_id)
    assembly = create_item(backend, kind="assembly", name="Frame")

    bom = backend.bom.replace_bom(
        backend.users["editor"],
        assembly.current_revision_id,
        [
            {
                "component_revision_id": component.current_revision_id,
                "quantity": Decimal("2.50"),
                "position": 1,
            }
        ],
    )
    assert bom[0]["component_revision_id"] == component.current_revision_id
    assert bom[0]["quantity"] == "2.5"
    assert bom[0]["item_number"] == component.number
    assert backend.bom.where_used(backend.users["editor"], component.id)[0][
        "parent_item_id"
    ] == assembly.id

    _release(backend, assembly.current_revision_id)
    revision_b, _ = backend.revisions.create_next_revision(
        backend.users["editor"], assembly.id, "Update the frame"
    )
    copied = backend.bom.get_bom(backend.users["editor"], revision_b.id)
    assert len(copied) == 1
    assert copied[0]["component_revision_id"] == component.current_revision_id


def test_assembly_release_waits_for_direct_components(backend):
    component = create_item(backend, name="Unreleased Bracket")
    assembly = create_item(backend, kind="assembly", name="Unreleased Frame")
    backend.bom.replace_bom(
        backend.users["editor"],
        assembly.current_revision_id,
        [
            {
                "component_revision_id": component.current_revision_id,
                "quantity": Decimal("1"),
                "position": 1,
            }
        ],
    )
    backend.revisions.check_in(backend.users["editor"], assembly.current_revision_id, "Assembly checked in")
    with pytest.raises(Conflict, match="component revisions must be Released"):
        backend.revisions.transition_lifecycle(
            backend.users["editor"], assembly.current_revision_id, LifecycleState.RELEASED
        )
    _release(backend, component.current_revision_id)
    backend.revisions.transition_lifecycle(
        backend.users["editor"], assembly.current_revision_id, LifecycleState.RELEASED
    )


def test_cycle_rejected_and_failed_bom_replace_rolls_back(backend):
    first = create_item(backend, kind="assembly", name="First")
    second = create_item(backend, kind="assembly", name="Second")
    backend.bom.replace_bom(
        backend.users["editor"],
        second.current_revision_id,
        [
            {
                "component_revision_id": first.current_revision_id,
                "quantity": Decimal("1"),
                "position": 1,
            }
        ],
    )
    with pytest.raises(Conflict, match="cycle"):
        backend.bom.replace_bom(
            backend.users["editor"],
            first.current_revision_id,
            [
                {
                    "component_revision_id": second.current_revision_id,
                    "quantity": Decimal("1"),
                    "position": 1,
                }
            ],
        )
    assert backend.bom.get_bom(backend.users["editor"], first.current_revision_id) == []
    assert len(backend.bom.get_bom(backend.users["editor"], second.current_revision_id)) == 1
