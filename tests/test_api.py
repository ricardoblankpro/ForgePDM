import hashlib
from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from forgepdm.application.auth import hash_password


def test_authenticated_item_file_lifecycle_api(tmp_path, monkeypatch):
    database_path = tmp_path / "api.sqlite3"
    file_root = tmp_path / "api-files"
    monkeypatch.setenv("FORGEPDM_DATABASE", str(tmp_path / "module-app.sqlite3"))
    monkeypatch.setenv("FORGEPDM_FILE_ROOT", str(file_root))

    # Import after setting isolated paths because the module also exports a default ASGI app.
    from forgepdm.main import create_app

    app = create_app(database_path)
    user_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with app.state.database.transaction() as connection:
        connection.execute(
            "INSERT INTO users(id, username, display_name, enabled, created_at, password_hash, role) "
            "VALUES (?, 'api-admin', 'API Admin', 1, ?, ?, 'admin')",
            (user_id, now, hash_password("api-test-password-12345")),
        )

    with TestClient(app) as client:
        assert client.get("/api/v1/items/00000000-0000-0000-0000-000000000000").status_code == 401
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "api-admin", "password": "api-test-password-12345"},
        )
        assert login.status_code == 200
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        created = client.post(
            "/api/v1/items",
            headers=headers,
            json={"kind": "part", "name": "API Part"},
        )
        assert created.status_code == 201
        item = created.json()
        assert item["number"] == "P000001"
        assert item["current_checkout"]["user_id"] == user_id

        content = b"CAD bytes uploaded through API"
        uploaded = client.post(
            f"/api/v1/revisions/{item['current_revision_id']}/datasets",
            headers=headers,
            data={"dataset_type": "native_cad", "name": "Native model"},
            files={"file": ("part.FCStd", content, "application/octet-stream")},
        )
        assert uploaded.status_code == 201
        file_record = uploaded.json()["files"][0]
        assert file_record["content_hash"] == hashlib.sha256(content).hexdigest()

        datasets = client.get(
            f"/api/v1/revisions/{item['current_revision_id']}/datasets", headers=headers
        )
        assert datasets.status_code == 200
        assert datasets.json()[0]["files"][0]["id"] == file_record["id"]
        download = client.get(file_record["download_url"], headers=headers)
        assert download.status_code == 200
        assert download.content == content

        checkin = client.post(
            f"/api/v1/revisions/{item['current_revision_id']}/checkin",
            headers=headers,
            json={"change_note": "First API check-in"},
        )
        assert checkin.status_code == 204
        release = client.post(
            f"/api/v1/revisions/{item['current_revision_id']}/lifecycle",
            headers=headers,
            json={"target": "released"},
        )
        assert release.status_code == 204

        next_revision = client.post(
            f"/api/v1/items/{item['id']}/revisions",
            headers=headers,
            json={"change_note": "Second API revision"},
        )
        assert next_revision.status_code == 201
        assert next_revision.json()["label"] == "B"

        assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
        assert client.get(f"/api/v1/items/{item['id']}", headers=headers).status_code == 401
