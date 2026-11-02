"""Management policies, mandatory password changes and scoped operational reads."""

import json
from uuid import uuid4

import pytest
from conftest import TEST_PASSWORD, create_item
from fastapi.testclient import TestClient

from forgepdm.application.auth import AuthenticationError
from forgepdm.application.management import ManagementService
from forgepdm.domain.entities import Conflict, Forbidden, NotFound
from forgepdm.main import create_app


@pytest.fixture
def management(backend):
    return ManagementService(backend.database)


@pytest.fixture
def client(backend, monkeypatch, tmp_path):
    monkeypatch.setenv("FORGEPDM_FILE_ROOT", str(tmp_path / "files"))
    with TestClient(create_app(backend.database.path)) as opened:
        yield opened


def headers(backend, name="admin"):
    token, _, _ = backend.auth.login(name, TEST_PASSWORD)
    return {"Authorization": "Bearer " + token}


def test_admin_creates_user_and_forced_password_blocks_all_engineering_access(backend, client):
    auth = headers(backend)
    response = client.post(
        "/api/v1/admin/users",
        headers=auth,
        json={"username": "test.person", "display_name": "Test", "password": "1234"},
    )
    assert response.status_code == 201, response.text
    user = response.json()
    assert user["must_change_password"] and "password_hash" not in user
    login = client.post(
        "/api/v1/auth/login", json={"username": "TEST.PERSON", "password": "1234"}
    ).json()
    token = {"Authorization": "Bearer " + login["access_token"]}
    assert login["user"]["must_change_password"]
    for path in ["/items", "/projects", "/me/checkouts", "/admin/users", "/activity"]:
        assert client.get("/api/v1" + path, headers=token).status_code == 403
    assert client.get("/api/v1/auth/me", headers=token).status_code == 200
    assert (
        client.post(
            "/api/v1/auth/password",
            headers=token,
            json={"current_password": "wrong", "new_password": "5678"},
        ).status_code
        == 403
    )
    changed = client.post(
        "/api/v1/auth/password",
        headers=token,
        json={"current_password": "1234", "new_password": "5678"},
    )
    assert changed.status_code == 200
    assert client.get("/api/v1/auth/me", headers=token).status_code == 401
    fresh = client.post(
        "/api/v1/auth/login", json={"username": "test.person", "password": "5678"}
    ).json()
    assert not fresh["user"]["must_change_password"]
    assert (
        client.get(
            "/api/v1/items", headers={"Authorization": "Bearer " + fresh["access_token"]}
        ).status_code
        == 200
    )
    duplicate = client.post(
        "/api/v1/admin/users",
        headers=auth,
        json={"username": "TEST.PERSON", "display_name": "Other", "password": "1234"},
    )
    assert duplicate.status_code == 409
    with backend.database.connection() as connection:
        records = " ".join(
            row[0] for row in connection.execute("SELECT details_json FROM audit_events")
        )
    assert "1234" not in records and "5678" not in records


def test_reset_disable_role_change_revoke_sessions(backend, management):
    admin, editor = backend.users["admin"], backend.users["editor"]
    token, _, _ = backend.auth.login("editor", TEST_PASSWORD)
    management.reset_password(admin, editor.id, "1234")
    with pytest.raises(AuthenticationError):
        backend.auth.authenticate(token)
    token, user, _ = backend.auth.login("editor", "1234")
    assert user.must_change_password
    management.change_password(user, "1234", "5678")
    token, _, _ = backend.auth.login("editor", "5678")
    management.update_user(admin, editor.id, "Editor", True, "admin")
    with pytest.raises(AuthenticationError):
        backend.auth.authenticate(token)
    token, _, _ = backend.auth.login("editor", "5678")
    management.update_user(admin, editor.id, "Editor", False, "admin")
    with pytest.raises(AuthenticationError):
        backend.auth.authenticate(token)
    with pytest.raises(AuthenticationError):
        backend.auth.login("editor", "5678")


def test_last_admin_and_stale_actor_protected(backend, management):
    admin = backend.users["admin"]
    with pytest.raises(Conflict, match="last active"):
        management.update_user(admin, admin.id, "Admin", False, "user")
    management.update_user(admin, backend.users["editor"].id, "Other admin", True, "admin")
    with pytest.raises(Conflict, match="own account"):
        management.update_user(admin, admin.id, "Admin", False, "user")
    with backend.database.transaction() as connection:
        connection.execute("UPDATE users SET role='user' WHERE id=?", (admin.id,))
    with pytest.raises(Forbidden):
        management.create_user(admin, "stale", "Stale", "1234")


def test_nonadmins_cannot_administer_users_projects_or_memberships(backend, client):
    auth = headers(backend, "editor")
    assert client.get("/api/v1/admin/users", headers=auth).status_code == 403
    for path, body in [
        ("/admin/users", {"username": "x", "display_name": "X", "password": "1234"}),
        ("/management/projects", {"project_number": "X", "name": "X"}),
    ]:
        assert client.post("/api/v1" + path, headers=auth, json=body).status_code == 403
    assert (
        client.get(
            f"/api/v1/management/projects/{backend.project_id}/members", headers=auth
        ).status_code
        == 403
    )
    assert (
        client.put(
            f"/api/v1/management/projects/{backend.project_id}/members/{backend.users['viewer'].id}",
            headers=auth,
            json={"role": "editor"},
        ).status_code
        == 403
    )


def project_values(**changes):
    return dict(
        project_number="PRJ-NEW",
        name="New",
        customer="Customer",
        due_date="2026-12-15",
        description="Project scope",
        archived=False,
        **changes,
    )


def test_project_properties_memberships_archive_and_access(backend, client):
    auth = headers(backend)
    response = client.post("/api/v1/management/projects", headers=auth, json=project_values())
    assert response.status_code == 201, response.text
    project = response.json()
    identifier = project["id"]
    assert project["due_date"] == "2026-12-15" and project["customer"] == "Customer"
    editor = headers(backend, "editor")
    assert identifier not in [
        p["id"] for p in client.get("/api/v1/management/projects", headers=editor).json()["items"]
    ]
    assert (
        client.get(f"/api/v1/activity?project_id={identifier}", headers=editor).status_code == 404
    )
    member = f"/api/v1/management/projects/{identifier}/members/{backend.users['editor'].id}"
    assert client.put(member, headers=auth, json={"role": "editor"}).status_code == 200
    assert identifier in [
        p["id"]
        for p in client.get("/api/v1/projects?editable=true", headers=editor).json()["items"]
    ]
    values = dict(project_values(), archived=True, customer="Changed")
    assert (
        client.put(
            f"/api/v1/management/projects/{identifier}", headers=auth, json=values
        ).status_code
        == 200
    )
    assert identifier not in [
        p["id"] for p in client.get("/api/v1/projects", headers=editor).json()["items"]
    ]
    archived = client.get(
        "/api/v1/management/projects?include_archived=true", headers=editor
    ).json()["items"]
    assert next(p for p in archived if p["id"] == identifier)["description"] == "Project scope"
    assert client.delete(member, headers=auth).status_code == 200
    assert identifier not in [
        p["id"]
        for p in client.get(
            "/api/v1/management/projects?include_archived=true", headers=editor
        ).json()["items"]
    ]
    assert (
        client.post("/api/v1/management/projects", headers=auth, json=project_values()).status_code
        == 409
    )


def test_my_checkouts_is_user_and_access_scoped_with_expired_status(backend, management):
    mine = create_item(backend)
    other = create_item(backend, user="editor2")
    assert [
        row["revision_id"] for row in management.checkouts(backend.users["editor"])["items"]
    ] == [mine.current_revision_id]
    with backend.database.transaction() as connection:
        connection.execute(
            "UPDATE checkouts SET expires_at='2020-01-01T00:00:00+00:00' WHERE revision_id=?",
            (mine.current_revision_id,),
        )
    assert management.checkouts(backend.users["editor"])["items"][0]["status"] == "expired"
    with backend.database.transaction() as connection:
        connection.execute(
            "DELETE FROM project_memberships WHERE user_id=?", (backend.users["editor"].id,)
        )
    assert management.checkouts(backend.users["editor"])["items"] == []
    assert (
        management.checkouts(backend.users["editor2"])["items"][0]["revision_id"]
        == other.current_revision_id
    )


def test_activity_filters_pagination_and_no_cross_project_disclosure(backend, management):
    visible = create_item(backend)
    private = create_item(backend, user="admin")
    admin = backend.users["admin"]
    viewer = backend.users["viewer"]
    with backend.database.transaction() as connection:
        connection.execute("DELETE FROM project_items WHERE item_id=?", (private.id,))
        management.audit(
            connection, admin, "test.private", "Item", private.id, {"secret": "private"}
        )
        management.audit(
            connection,
            admin,
            "test.visible",
            "ItemRevision",
            visible.current_revision_id,
            {"private_component": private.id},
        )
    scoped = management.activity(viewer, query="test.")["items"]
    assert len(scoped) == 1 and scoped[0]["event_type"] == "test.visible"
    assert "details" not in scoped[0]
    assert private.id not in json.dumps(scoped)
    assert len(management.activity(admin, query="test.")["items"]) == 2
    with backend.database.transaction() as connection:
        management.audit(
            connection, backend.users["editor2"], "test.hidden_actor", "Item", private.id
        )
    assert "editor2" not in [row["username"] for row in management.activity_actors(viewer)["items"]]
    assert "editor2" in [row["username"] for row in management.activity_actors(admin)["items"]]
    filtered = management.activity(
        viewer, project_id=backend.project_id, action="test.visible", actor_id=admin.id
    )["items"]
    assert len(filtered) == 1
    assert management.activity(viewer, start="2099-01-01")["items"] == []
    page = management.activity(admin, limit=1)
    assert page["has_more"] and len(page["items"]) == 1
    assert page["items"][0]["id"] != management.activity(admin, limit=1, offset=1)["items"][0]["id"]
    with pytest.raises(ValueError):
        management.activity(viewer, start="2026-12-01", end="2026-01-01")
    with pytest.raises(NotFound):
        management.activity(viewer, project_id=str(uuid4()))


def test_management_api_validation_and_unauthenticated_access(backend, client):
    for path in ["/admin/users", "/management/projects", "/me/checkouts", "/activity"]:
        assert client.get("/api/v1" + path).status_code == 401
    auth = headers(backend)
    bad = dict(project_values(), due_date="2026-02-30")
    assert client.post("/api/v1/management/projects", headers=auth, json=bad).status_code == 422
    assert client.get("/api/v1/activity?actor_id=bad", headers=auth).status_code == 422
    assert client.get("/api/v1/admin/users?limit=101", headers=auth).status_code == 422


def test_migration_8_preserves_existing_accounts_projects_and_leases(backend):
    from forgepdm.infrastructure.database import Database

    item = create_item(backend)
    token, _, _ = backend.auth.login("editor", TEST_PASSWORD)
    with backend.database.transaction() as connection:
        original_user = dict(
            connection.execute(
                "SELECT id,username,password_hash,enabled,role FROM users WHERE id=?",
                (backend.users["editor"].id,),
            ).fetchone()
        )
        original_lease = dict(
            connection.execute(
                "SELECT * FROM checkouts WHERE revision_id=?", (item.current_revision_id,)
            ).fetchone()
        )
        connection.execute("DROP INDEX audit_events_time_idx")
        for column in ("customer", "due_date", "description"):
            connection.execute(f"ALTER TABLE projects DROP COLUMN {column}")
        connection.execute("ALTER TABLE users DROP COLUMN must_change_password")
        connection.execute("DELETE FROM schema_version WHERE version=8")
    database = Database(backend.database.path)
    database.initialize()
    database.initialize()
    with database.connection() as connection:
        assert (
            dict(
                connection.execute(
                    "SELECT id,username,password_hash,enabled,role FROM users WHERE id=?",
                    (backend.users["editor"].id,),
                ).fetchone()
            )
            == original_user
        )
        assert (
            dict(
                connection.execute(
                    "SELECT * FROM checkouts WHERE revision_id=?", (item.current_revision_id,)
                ).fetchone()
            )
            == original_lease
        )
        assert (
            connection.execute(
                "SELECT must_change_password FROM users WHERE id=?", (backend.users["editor"].id,)
            ).fetchone()[0]
            == 0
        )
        project = connection.execute(
            "SELECT customer,due_date,description FROM projects WHERE id=?", (backend.project_id,)
        ).fetchone()
        assert tuple(project) == ("", None, "")
    assert backend.auth.authenticate(token).id == backend.users["editor"].id
