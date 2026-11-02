"""Browser shell packaging and project-scoped authorization contracts."""

from datetime import UTC, datetime
from uuid import uuid4

from conftest import TEST_PASSWORD, create_item
from fastapi.testclient import TestClient

from forgepdm.application.catalog import CatalogService


def test_web_shell_and_assets_are_public_but_data_remains_authenticated(
    backend, monkeypatch, tmp_path
):
    monkeypatch.setenv("FORGEPDM_FILE_ROOT", str(tmp_path / "files"))
    from forgepdm.main import create_app

    with TestClient(create_app(backend.database.path)) as client:
        response = client.get("/app/")
        assert response.status_code == 200
        assert "Welcome to ForgePDM" in response.text
        assert "script-src 'self'" in response.headers["content-security-policy"]
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        for name in ["style.css", "app.mjs", "model.mjs", "api.mjs", "management.mjs", "mark.svg"]:
            asset = client.get("/app/" + name)
            assert asset.status_code == 200
        assert client.get("/api/v1/items").status_code == 401
        assert client.get("/app/missing.mjs").status_code == 404


def test_project_filter_cannot_disclose_membership_in_hidden_project(backend):
    item = create_item(backend, name="Shared item")
    now = datetime.now(UTC).isoformat()
    hidden = str(uuid4())
    with backend.database.transaction() as connection:
        connection.execute(
            "INSERT INTO projects(id,project_number,name,archived,created_at) VALUES (?, 'HIDDEN', 'Hidden', 0, ?)",
            (hidden, now),
        )
        connection.execute(
            "INSERT INTO project_items(project_id,item_id,added_at) VALUES (?, ?, ?)",
            (hidden, item.id, now),
        )
    catalog = CatalogService(backend.database, backend.authorization)
    assert (
        catalog.search_items(backend.users["viewer"], project_id=backend.project_id)["items"][0][
            "id"
        ]
        == item.id
    )
    assert catalog.search_items(backend.users["viewer"], project_id=hidden)["items"] == []
    assert (
        catalog.search_items(backend.users["admin"], project_id=hidden)["items"][0]["id"] == item.id
    )
    with backend.database.transaction() as connection:
        connection.execute("UPDATE projects SET archived=1 WHERE id=?", (hidden,))
    assert catalog.search_items(backend.users["admin"], project_id=hidden)["items"] == []


def test_project_filter_paginates_after_scope_and_validates_uuid(backend, monkeypatch, tmp_path):
    create_item(backend, name="First")
    create_item(backend, name="Second")
    monkeypatch.setenv("FORGEPDM_FILE_ROOT", str(tmp_path / "files"))
    from forgepdm.main import create_app

    with TestClient(create_app(backend.database.path)) as client:
        token = client.post(
            "/api/v1/auth/login", json={"username": "viewer", "password": TEST_PASSWORD}
        ).json()["access_token"]
        headers = {"Authorization": "Bearer " + token}
        query = f"/api/v1/items?project_id={backend.project_id}&limit=1"
        first = client.get(query, headers=headers).json()
        second = client.get(query + "&offset=1", headers=headers).json()
        assert first["has_more"] and not second["has_more"]
        assert first["items"][0]["id"] != second["items"][0]["id"]
        assert client.get("/api/v1/items?project_id=invalid", headers=headers).status_code == 422
