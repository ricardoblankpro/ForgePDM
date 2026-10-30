"""Catalog queries must filter permissions before pagination and selection."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from forgepdm.application.catalog import CatalogService
from forgepdm.domain.entities import Forbidden, ItemKind, LifecycleState

from conftest import TEST_PASSWORD, create_item


def catalog(backend):
    return CatalogService(backend.database, backend.authorization)


def test_catalog_filters_projects_and_items_before_pagination(backend):
    public = create_item(backend, name="Visible bracket")
    private = backend.items.create_item(
        kind=ItemKind.PART,
        name="Private bracket",
        description="secret",
        created_by=backend.users["admin"].id,
    )
    service = catalog(backend)
    result = service.search_items(backend.users["viewer"], query="bracket", limit=1)
    assert [item["id"] for item in result["items"]] == [public.id]
    assert not result["has_more"]
    assert service.search_items(backend.users["viewer"], query=private.number)["items"] == []
    assert len(service.search_items(backend.users["admin"])["items"]) == 2
    assert service.projects(backend.users["viewer"], editable=True)["items"] == []
    assert service.projects(backend.users["viewer"])["items"][0]["can_edit"] is False
    assert (
        service.projects(backend.users["editor"], editable=True)["items"][0]["id"]
        == backend.project_id
    )


def test_search_is_literal_paginated_and_matches_description(backend):
    one = create_item(backend, name="100% bracket")
    two = create_item(backend, name="Another bracket")
    service = catalog(backend)
    user = backend.users["editor"]
    assert service.search_items(user, query="%", limit=1)["items"][0]["id"] == one.id
    first = service.search_items(user, query="BRACKET", limit=1)
    assert first["has_more"]
    assert (
        service.search_items(user, query="bracket", limit=1, offset=1)["items"][0]["id"] == two.id
    )
    assert len(service.search_items(user, query="Created in a test")["items"]) == 2
    assert service.search_items(user, query="' OR 1=1 --")["items"] == []
    with pytest.raises(ValueError):
        service.search_items(user, limit=101)


def test_revision_history_and_lookup_keep_explicit_identity(backend):
    item = create_item(backend)
    user = backend.users["editor"]
    backend.revisions.check_in(user, item.current_revision_id, "Complete A")
    backend.revisions.transition_lifecycle(user, item.current_revision_id, LifecycleState.RELEASED)
    revision_b, _checkout = backend.revisions.create_next_revision(user, item.id, "Begin B")
    service = catalog(backend)
    rows = service.revisions(user, item.id)["items"]
    assert [row["label"] for row in rows] == ["B", "A"]
    assert rows[1]["id"] == item.current_revision_id
    assert service.revision(user, item.current_revision_id)["label"] == "A"
    private = backend.items.create_item(
        kind=ItemKind.PART, name="Private", description="", created_by=backend.users["admin"].id
    )
    with pytest.raises(Forbidden):
        service.revisions(user, private.id)
    with pytest.raises(Forbidden):
        service.revision(user, private.current_revision_id)
    assert service.revision(user, revision_b.id)["item_number"] == item.number


def test_archived_and_unassigned_projects_not_offered(backend):
    service = catalog(backend)
    with backend.database.transaction() as connection:
        connection.execute(
            "INSERT INTO projects(id, project_number, name, archived, created_at) VALUES (?, 'OTHER', 'Other', 0, ?)",
            (str(uuid4()), datetime.now(timezone.utc).isoformat()),
        )
    assert len(service.projects(backend.users["editor"])["items"]) == 1
    with backend.database.transaction() as connection:
        connection.execute("UPDATE projects SET archived=1 WHERE id=?", (backend.project_id,))
    assert service.projects(backend.users["editor"])["items"] == []


def test_catalog_api_authentication_bounds_and_non_disclosure(backend, monkeypatch, tmp_path):
    monkeypatch.setenv("FORGEPDM_DATABASE", str(backend.database.path))
    monkeypatch.setenv("FORGEPDM_FILE_ROOT", str(tmp_path / "api-files"))
    from forgepdm.main import create_app

    visible = create_item(backend)
    private = backend.items.create_item(
        kind=ItemKind.PART, name="Private", description="", created_by=backend.users["admin"].id
    )
    app = create_app(backend.database.path)
    with TestClient(app) as client:
        assert client.get("/api/v1/items").status_code == 401
        token = client.post(
            "/api/v1/auth/login", json={"username": "viewer", "password": TEST_PASSWORD}
        ).json()["access_token"]
        headers = {"Authorization": "Bearer " + token}
        assert client.get("/api/v1/items?limit=101", headers=headers).status_code == 422
        assert client.get("/api/v1/items?offset=-1", headers=headers).status_code == 422
        assert client.get("/api/v1/projects?editable=true", headers=headers).json()["items"] == []
        assert (
            client.get("/api/v1/items?q=" + visible.number, headers=headers).json()["items"][0][
                "id"
            ]
            == visible.id
        )
        assert (
            client.get(f"/api/v1/items/{private.id}/revisions", headers=headers).status_code == 404
        )
        assert (
            client.get(
                f"/api/v1/revisions/{private.current_revision_id}", headers=headers
            ).status_code
            == 404
        )
        assert (
            client.get(f"/api/v1/revisions/{visible.current_revision_id}", headers=headers).json()[
                "label"
            ]
            == "A"
        )
