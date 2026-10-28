"""Isolated backend fixtures for service and API tests."""

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from forgepdm.application.auth import AuthService, hash_password
from forgepdm.application.authorization import AuthorizationService
from forgepdm.application.bom import BOMService
from forgepdm.application.datasets import DatasetService
from forgepdm.application.items import ItemService
from forgepdm.application.revisions import RevisionService
from forgepdm.domain.entities import User
from forgepdm.infrastructure.database import Database
from forgepdm.infrastructure.storage import FileStorage


TEST_PASSWORD = "test-password-0123456789"


@pytest.fixture
def backend(tmp_path: Path):
    database = Database(tmp_path / "forgepdm.sqlite3")
    database.initialize()
    database.initialize()

    now = datetime.now(timezone.utc).isoformat()
    users = {
        name: {
            "id": str(uuid4()),
            "username": name,
            "display_name": name.title(),
            "role": role,
        }
        for name, role in (
            ("admin", "admin"),
            ("editor", "user"),
            ("editor2", "user"),
            ("viewer", "user"),
        )
    }
    project_id = str(uuid4())
    password_hash = hash_password(TEST_PASSWORD)
    with database.transaction() as connection:
        for user in users.values():
            connection.execute(
                "INSERT INTO users(id, username, display_name, enabled, created_at, password_hash, role) "
                "VALUES (?, ?, ?, 1, ?, ?, ?)",
                (
                    user["id"],
                    user["username"],
                    user["display_name"],
                    now,
                    password_hash,
                    user["role"],
                ),
            )
        connection.execute(
            "INSERT INTO projects(id, project_number, name, archived, created_at) VALUES (?, ?, ?, 0, ?)",
            (project_id, "PRJ-TEST", "Test Project", now),
        )
        for username, project_role in (
            ("editor", "editor"),
            ("editor2", "editor"),
            ("viewer", "viewer"),
        ):
            connection.execute(
                "INSERT INTO project_memberships(project_id, user_id, role, granted_at) VALUES (?, ?, ?, ?)",
                (project_id, users[username]["id"], project_role, now),
            )

    domain_users = {
        name: User(
            id=user["id"],
            username=user["username"],
            display_name=user["display_name"],
            enabled=True,
            role=user["role"],
        )
        for name, user in users.items()
    }
    authorization = AuthorizationService(database)
    storage = FileStorage(tmp_path / "files", max_upload_bytes=16)
    revisions = RevisionService(database, authorization)
    return SimpleNamespace(
        database=database,
        users=domain_users,
        user_rows=users,
        project_id=project_id,
        auth=AuthService(database),
        authorization=authorization,
        storage=storage,
        revisions=revisions,
        items=ItemService(database),
        datasets=DatasetService(database, storage, authorization, revisions),
        bom=BOMService(database, authorization, revisions),
    )


def create_item(backend, *, kind="part", user="editor", name="Test Item"):
    from forgepdm.domain.entities import ItemKind

    return backend.items.create_item(
        kind=ItemKind(kind),
        name=name,
        description="Created in a test",
        created_by=backend.users[user].id,
        project_id=backend.project_id,
    )
