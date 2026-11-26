from uuid import uuid4

import pytest
from conftest import create_item

from forgepdm.domain.entities import Conflict


def test_cancel_replay_does_not_release_a_later_checkout(backend):
    item = create_item(backend)
    user = backend.users["editor"]
    service = backend.revisions
    revision = item.current_revision_id
    checkout = service.current_checkout(user, revision)
    operation = str(uuid4())
    result = service.cancel_checkout(user, revision, operation, checkout.id, checkout.version)
    assert service.current_checkout(user, revision) is None
    later = service.acquire_checkout(user, revision)
    assert (
        service.cancel_checkout(user, revision, operation, checkout.id, checkout.version) == result
    )
    assert service.current_checkout(user, revision).id == later.id
    assert service.cancellation_status(user, revision, operation) == result
    assert service.cancellation_status(backend.users["editor2"], revision, operation) is None
    with pytest.raises(Conflict, match="different intent"):
        service.cancel_checkout(user, revision, operation, later.id, later.version)


def test_cancel_rejects_renewed_and_other_owner_leases(backend):
    item = create_item(backend)
    user = backend.users["editor"]
    service = backend.revisions
    revision = item.current_revision_id
    old = service.current_checkout(user, revision)
    current = service.renew_checkout(user, revision)
    with pytest.raises(Conflict, match="checkout changed"):
        service.cancel_checkout(user, revision, str(uuid4()), old.id, old.version)
    with pytest.raises(Conflict, match="owned"):
        service.cancel_checkout(
            backend.users["editor2"], revision, str(uuid4()), current.id, current.version
        )
    with pytest.raises(Conflict, match="snapshot changed"):
        service.cancel_checkout(
            user, revision, str(uuid4()), current.id, current.version, "wrong", "wrong"
        )
    assert service.current_checkout(user, revision).id == current.id


def test_cancellation_preserves_uploaded_history_and_detects_snapshot_races(backend):
    from test_atomic_checkin import intent, service

    item = create_item(backend)
    user = backend.users["editor"]
    revision = item.current_revision_id
    first = service(backend).check_in(**intent(backend, item, keep_checkout=True))
    old = first["dataset"]
    checkout = backend.revisions.current_checkout(user, revision)
    second = service(backend).check_in(**intent(backend, item, keep_checkout=True))
    current = second["dataset"]
    with pytest.raises(Conflict, match="snapshot changed"):
        backend.revisions.cancel_checkout(
            user,
            revision,
            str(uuid4()),
            checkout.id,
            checkout.version,
            old["id"],
            old["files"][0]["id"],
        )
    backend.revisions.cancel_checkout(
        user,
        revision,
        str(uuid4()),
        checkout.id,
        checkout.version,
        current["id"],
        current["files"][0]["id"],
    )
    with backend.database.connection() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM datasets WHERE revision_id=?", (revision,)
            ).fetchone()[0]
            == 2
        )
    assert backend.revisions.current_checkout(user, revision) is None


def test_cancellation_api_replays_only_the_original_lease(backend, monkeypatch, tmp_path):
    from conftest import TEST_PASSWORD
    from fastapi.testclient import TestClient

    from forgepdm.main import create_app

    monkeypatch.setenv("FORGEPDM_FILE_ROOT", str(tmp_path / "api-files"))
    item = create_item(backend)
    revision = item.current_revision_id
    user = backend.users["editor"]
    checkout = backend.revisions.current_checkout(user, revision)
    token, _, _ = backend.auth.login("editor", TEST_PASSWORD)
    headers = {"Authorization": "Bearer " + token}
    payload = dict(
        operation_id=str(uuid4()),
        expected_checkout_id=checkout.id,
        expected_checkout_version=checkout.version,
        dataset_id=None,
        file_id=None,
    )
    with TestClient(create_app(backend.database.path)) as client:
        route = f"/api/v1/revisions/{revision}/checkout/cancel"
        response = client.post(route, headers=headers, json=payload)
        assert response.status_code == 200, response.text
        later = backend.revisions.acquire_checkout(user, revision)
        assert client.post(route, headers=headers, json=payload).json() == response.json()
        status = client.get(
            f"/api/v1/revisions/{revision}/checkout/cancel-operations/{payload['operation_id']}",
            headers=headers,
        )
        assert status.json() == response.json()
        assert backend.revisions.current_checkout(user, revision).id == later.id
