from datetime import datetime, timedelta, timezone

import pytest

from forgepdm.domain.entities import Conflict, ItemKind, LifecycleState

from conftest import create_item


def test_migrations_are_repeatable_and_item_creation_is_atomic(backend):
    with backend.database.connection() as connection:
        versions = [row["version"] for row in connection.execute("SELECT version FROM schema_version ORDER BY version")]
    assert versions == [1, 2, 3, 4, 5, 6]

    first = create_item(backend, kind="part")
    second = create_item(backend, kind="assembly", name="Test Assembly")
    assert first.number == "P000001"
    assert second.number == "A000001"
    assert first.current_revision_id
    checkout = backend.revisions.current_checkout(
        backend.users["editor"], first.current_revision_id
    )
    assert checkout is not None
    assert checkout.user_id == backend.users["editor"].id


def test_checkout_is_exclusive_and_expired_lease_can_be_reclaimed(backend):
    item = create_item(backend)
    with pytest.raises(Conflict):
        backend.revisions.acquire_checkout(
            backend.users["editor2"], item.current_revision_id
        )

    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    with backend.database.transaction() as connection:
        connection.execute(
            "UPDATE checkouts SET expires_at = ? WHERE revision_id = ? AND released_at IS NULL",
            (past, item.current_revision_id),
        )
    new_lease = backend.revisions.acquire_checkout(
        backend.users["editor2"], item.current_revision_id
    )
    assert new_lease.user_id == backend.users["editor2"].id
    with backend.database.connection() as connection:
        history = connection.execute(
            "SELECT released_at, release_reason FROM checkouts WHERE revision_id = ? ORDER BY acquired_at",
            (item.current_revision_id,),
        ).fetchall()
    assert history[0]["released_at"] is not None
    assert history[0]["release_reason"] == "expired"


def test_admin_checkout_override_requires_and_records_reason(backend):
    item = create_item(backend)
    with pytest.raises(ValueError):
        backend.revisions.release_checkout(backend.users["admin"], item.current_revision_id)
    released = backend.revisions.release_checkout(
        backend.users["admin"], item.current_revision_id, "Owner unavailable"
    )
    assert released.released_at is not None
    with backend.database.connection() as connection:
        event = connection.execute(
            "SELECT details_json FROM audit_events WHERE event_type = 'checkout.released'"
        ).fetchone()
    assert "Owner unavailable" in event["details_json"]


def test_checkin_release_and_next_revision_workflow(backend):
    item = create_item(backend)
    revision_a = item.current_revision_id

    with pytest.raises(Conflict):
        backend.revisions.transition_lifecycle(
            backend.users["editor"], revision_a, LifecycleState.RELEASED
        )
    backend.revisions.check_in(backend.users["editor"], revision_a, "Initial design complete")
    assert backend.revisions.current_checkout(backend.users["editor"], revision_a) is None
    backend.revisions.transition_lifecycle(
        backend.users["editor"], revision_a, LifecycleState.RELEASED
    )
    with pytest.raises(Conflict):
        backend.revisions.transition_lifecycle(
            backend.users["editor"], revision_a, LifecycleState.WORKING
        )

    revision_b, checkout_b = backend.revisions.create_next_revision(
        backend.users["editor"], item.id, "Add mounting holes"
    )
    assert revision_b.label == "B"
    assert revision_b.lifecycle_state == LifecycleState.WORKING
    assert checkout_b.user_id == backend.users["editor"].id
    item_after, current = backend.items.get_item(item.id)
    assert item_after.current_revision_id == revision_b.id
    assert current.id == revision_b.id


def test_revision_label_extends_beyond_z(backend):
    item = create_item(backend)
    previous_id = item.current_revision_id
    for sequence in range(1, 28):
        backend.revisions.check_in(backend.users["editor"], previous_id, f"Check in {sequence}")
        backend.revisions.transition_lifecycle(
            backend.users["editor"], previous_id, LifecycleState.RELEASED
        )
        revision, _ = backend.revisions.create_next_revision(
            backend.users["editor"], item.id, f"Revision {sequence + 1}"
        )
        previous_id = revision.id
    assert revision.label == "AB"
