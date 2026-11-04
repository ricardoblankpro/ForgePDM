"""Status reads must preserve access boundaries and exact revision semantics."""

import io
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from conftest import TEST_PASSWORD, create_item
from fastapi.testclient import TestClient

from forgepdm.application.tree_status import TreeStatusService
from forgepdm.domain.entities import DatasetType, ItemKind, LifecycleState


def service(backend):
    return TreeStatusService(backend.database, backend.authorization)


def test_status_reports_owner_and_distinguishes_mine_without_exposing_account_data(backend):
    item = create_item(backend)
    owner = backend.users["editor"]
    row = service(backend).revisions(owner, [item.current_revision_id])["items"][0]
    assert row["checkout"]["is_mine"] is True
    assert row["checkout"]["display_name"] == "Editor"
    other = service(backend).revisions(backend.users["viewer"], [item.current_revision_id])[
        "items"
    ][0]
    assert other["checkout"]["is_mine"] is False
    assert set(other["checkout"]) == {
        "user_id",
        "username",
        "display_name",
        "expires_at",
        "is_mine",
    }
    assert other["latest_snapshot"] is None and other["newer_revision"] is None


def test_expired_and_released_leases_are_not_presented_as_owned(backend):
    item = create_item(backend)
    with backend.database.transaction() as connection:
        connection.execute(
            "UPDATE checkouts SET expires_at=? WHERE revision_id=?",
            (
                (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
                item.current_revision_id,
            ),
        )
    assert (
        service(backend).revisions(backend.users["viewer"], [item.current_revision_id])["items"][0][
            "checkout"
        ]
        is None
    )


def test_released_revision_newer_revision_and_latest_snapshot_are_independent(backend):
    item = create_item(backend)
    user = backend.users["editor"]
    one, _ = backend.datasets.attach_file(
        user=user,
        revision_id=item.current_revision_id,
        dataset_type=DatasetType.NATIVE_CAD,
        dataset_name="one",
        filename="one.FCStd",
        media_type="application/octet-stream",
        source=io.BytesIO(b"one"),
    )
    two, file = backend.datasets.attach_file(
        user=user,
        revision_id=item.current_revision_id,
        dataset_type=DatasetType.NATIVE_CAD,
        dataset_name="two",
        filename="two.FCStd",
        media_type="application/octet-stream",
        source=io.BytesIO(b"two"),
    )
    backend.revisions.check_in(user, item.current_revision_id, "finish")
    backend.revisions.transition_lifecycle(user, item.current_revision_id, LifecycleState.RELEASED)
    newer, _ = backend.revisions.create_next_revision(user, item.id, "next")
    row = service(backend).revisions(user, [item.current_revision_id])["items"][0]
    assert row["lifecycle_state"] == "released" and row["checkout"] is None
    assert row["newer_revision"] == {"id": newer.id, "label": "B"}
    assert row["latest_snapshot"]["dataset_id"] == two.id != one.id
    assert row["latest_snapshot"]["file_id"] == file.id
    assert "storage_key" not in str(row) and "password" not in str(row)
    with backend.database.transaction() as connection:
        connection.execute(
            "UPDATE item_revisions SET lifecycle_state='obsolete' WHERE id=?", (newer.id,)
        )
    assert (
        service(backend).revisions(user, [item.current_revision_id])["items"][0]["newer_revision"]
        is None
    )


def test_private_missing_and_removed_access_are_indistinguishable(backend):
    visible = create_item(backend)
    private = backend.items.create_item(
        kind=ItemKind.PART, name="secret", description="", created_by=backend.users["admin"].id
    )
    missing = str(uuid4())
    ids = [
        private.current_revision_id,
        missing,
        visible.current_revision_id,
        visible.current_revision_id,
    ]
    rows = service(backend).revisions(backend.users["viewer"], ids)["items"]
    assert len(rows) == 3
    assert rows[:2] == [{"revision_id": value, "available": False} for value in ids[:2]]
    assert rows[2]["available"]
    with backend.database.transaction() as connection:
        connection.execute(
            "DELETE FROM project_memberships WHERE user_id=?", (backend.users["viewer"].id,)
        )
    assert service(backend).revisions(backend.users["viewer"], [visible.current_revision_id])[
        "items"
    ] == [{"revision_id": visible.current_revision_id, "available": False}]


def test_api_requires_auth_validates_bounds_and_disables_caching(backend, monkeypatch, tmp_path):
    monkeypatch.setenv("FORGEPDM_FILE_ROOT", str(tmp_path / "api-files"))
    monkeypatch.setenv("FORGEPDM_DATABASE", str(backend.database.path))
    from forgepdm.main import create_app

    item = create_item(backend)
    with TestClient(create_app(backend.database.path)) as client:
        endpoint = "/api/v1/status/revisions"
        body = {"revision_ids": [item.current_revision_id]}
        assert client.post(endpoint, json=body).status_code == 401
        token = client.post(
            "/api/v1/auth/login", json={"username": "viewer", "password": TEST_PASSWORD}
        ).json()["access_token"]
        headers = {"Authorization": "Bearer " + token}
        for ids in ([], ["invalid"], [item.current_revision_id] * 201):
            assert (
                client.post(endpoint, headers=headers, json={"revision_ids": ids}).status_code
                == 422
            )
        response = client.post(endpoint, headers=headers, json=body)
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        assert response.json()["items"][0]["available"]
