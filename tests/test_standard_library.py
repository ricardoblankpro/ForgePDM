"""Shared library ownership, migration preservation and ordinary-project isolation."""

from uuid import uuid4

import pytest
from conftest import TEST_PASSWORD
from fastapi.testclient import TestClient

from forgepdm.application.catalog import CatalogService
from forgepdm.application.management import ManagementService
from forgepdm.domain.entities import Conflict, Forbidden, ItemKind
from forgepdm.infrastructure.database import MIGRATIONS, Database


def library_id(backend):
    with backend.database.connection() as connection:
        return connection.execute("SELECT id FROM projects WHERE is_standard_library=1").fetchone()[
            0
        ]


def create_standard(backend, actor="editor", project_id=None):
    return backend.items.create_item(
        kind=ItemKind.PART,
        number_series="S",
        name="Shared bolt",
        description="",
        created_by=backend.users[actor].id,
        project_id=project_id,
    )


def test_shared_creation_ignores_consuming_project_and_requires_library_maintainer(backend):
    item = create_standard(backend, project_id=backend.project_id)
    lib = library_id(backend)
    with backend.database.connection() as connection:
        assert [
            row[0]
            for row in connection.execute(
                "SELECT project_id FROM project_items WHERE item_id=?", (item.id,)
            )
        ] == [lib]
    # An engineer is an editor of the consuming project, but only a library reader.
    with pytest.raises(Forbidden, match="maintainer"):
        create_standard(backend, actor="editor2", project_id=backend.project_id)
    for actor in ("viewer", "editor2"):
        backend.authorization.require_read_revision(backend.users[actor], item.current_revision_id)
        with pytest.raises(Forbidden):
            backend.authorization.require_edit_revision(
                backend.users[actor], item.current_revision_id
            )
    backend.authorization.require_edit_revision(backend.users["editor"], item.current_revision_id)


def test_bom_reuse_does_not_grant_library_write_rights(backend):
    child = create_standard(backend)
    parent = backend.items.create_item(
        kind=ItemKind.ASSEMBLY,
        name="Another project assembly",
        description="",
        created_by=backend.users["editor2"].id,
        project_id=backend.project_id,
    )
    backend.bom.replace_bom(
        backend.users["editor2"],
        parent.current_revision_id,
        [dict(component_revision_id=child.current_revision_id, quantity=2, position=1)],
    )
    assert (
        backend.bom.get_bom(backend.users["viewer"], parent.current_revision_id)[0]["quantity"]
        == "2"
    )
    with pytest.raises(Forbidden):
        backend.revisions.acquire_checkout(backend.users["editor2"], child.current_revision_id)
    with backend.database.connection() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM project_items WHERE item_id=?", (child.id,)
            ).fetchone()[0]
            == 1
        )


def test_library_is_visible_but_not_an_engineering_item_destination(backend):
    catalog = CatalogService(backend.database, backend.authorization)
    assert any(
        row["is_standard_library"] for row in catalog.projects(backend.users["viewer"])["items"]
    )
    assert all(
        not row["is_standard_library"]
        for row in catalog.projects(backend.users["admin"], editable=True)["items"]
    )
    with pytest.raises(ValueError, match="S/M items only"):
        backend.items.create_item(
            kind=ItemKind.PART,
            name="Wrong destination",
            description="",
            created_by=backend.users["admin"].id,
            project_id=library_id(backend),
        )


def test_library_cannot_be_archived_and_new_users_get_reader_access(backend):
    service = ManagementService(backend.database)
    lib = library_id(backend)
    with backend.database.connection() as connection:
        project = service.project_access(connection, backend.users["admin"], lib)
    with pytest.raises(Conflict, match="cannot be archived"):
        service.save_project(backend.users["admin"], dict(project, archived=True), lib)
    user = service.create_user(backend.users["admin"], "new-engineer", "New Engineer", "1234")
    with backend.database.connection() as connection:
        assert (
            connection.execute(
                "SELECT role FROM project_memberships WHERE project_id=? AND user_id=?",
                (lib, user["id"]),
            ).fetchone()[0]
            == "viewer"
        )
    # Explicit removal is not reversed by unrelated account updates.
    service.membership(backend.users["admin"], lib, user["id"], None)
    service.update_user(backend.users["admin"], user["id"], "Renamed Engineer", True, "user")
    with backend.database.connection() as connection:
        assert (
            connection.execute(
                "SELECT 1 FROM project_memberships WHERE project_id=? AND user_id=?",
                (lib, user["id"]),
            ).fetchone()
            is None
        )


def test_library_api_routes_creation_and_reports_permissions(backend, tmp_path, monkeypatch):
    monkeypatch.setenv("FORGEPDM_DATABASE", str(tmp_path / "default.sqlite3"))
    monkeypatch.setenv("FORGEPDM_FILE_ROOT", str(tmp_path / "files"))
    from forgepdm.main import create_app

    with TestClient(create_app(backend.database.path)) as client:

        def headers(name):
            token = client.post(
                "/api/v1/auth/login", json={"username": name, "password": TEST_PASSWORD}
            ).json()["access_token"]
            return {"Authorization": "Bearer " + token}

        maintainer, engineer = headers("editor"), headers("editor2")
        capabilities = client.get("/api/v1/standard-parts/capabilities", headers=engineer).json()
        assert capabilities["shared_library"] and not capabilities["can_register"]
        assert client.get("/api/v1/standard-parts/capabilities", headers=maintainer).json()[
            "can_register"
        ]
        payload = dict(kind="part", number_series="S", name="Library part")
        created = client.post("/api/v1/items", json=payload, headers=maintainer)
        assert created.status_code == 201
        assert (
            client.post(
                "/api/v1/items", json=dict(payload, project_id=backend.project_id), headers=engineer
            ).status_code
            == 403
        )
        assert (
            client.get("/api/v1/items/" + created.json()["id"], headers=engineer).status_code == 200
        )


def test_migration_moves_s_ownership_without_merging_or_repinning(tmp_path):
    database = Database(tmp_path / "old.sqlite3")
    creator, engineer, project, second_project = [str(uuid4()) for _ in range(4)]
    items = []
    with database.connect() as connection:
        for version, sql in MIGRATIONS:
            if version >= 12:
                break
            connection.executescript(sql)
            connection.execute("INSERT INTO schema_version VALUES (?,'before')", (version,))
        connection.execute("BEGIN")
        for identifier, name in [(creator, "creator"), (engineer, "engineer")]:
            connection.execute(
                "INSERT INTO users(id,username,display_name,enabled,created_at) VALUES (?,?,?,1,'before')",
                (identifier, name, name),
            )
        for identifier, number in [(project, "LIB-STANDARD"), (second_project, "PRJ-OTHER")]:
            connection.execute(
                "INSERT INTO projects(id,project_number,name,archived,created_at) VALUES (?,?,?,0,'before')",
                (identifier, number, number),
            )
        connection.execute(
            "INSERT INTO project_memberships VALUES (?,?,'editor','before')", (project, engineer)
        )
        for index in range(3):
            item, revision = str(uuid4()), str(uuid4())
            items.append((item, revision))
            connection.execute(
                "INSERT INTO items(id,number,kind,name,created_by,created_at,current_revision_id,number_series) VALUES (?,?,'part',?,?, 'before',?,'S')",
                (item, "S" + str(index + 1).zfill(6), "Old name " + str(index), creator, revision),
            )
            connection.execute(
                "INSERT INTO item_revisions(id,item_id,label,sequence,lifecycle_state,created_by,created_at) VALUES (?,?,'A',1,'working',?,'before')",
                (revision, item, creator),
            )
            scope = project if index != 1 else second_project
            connection.execute("INSERT INTO project_items VALUES (?,?,'before')", (scope, item))
            value = "same-specification" if index < 2 else "unique-specification"
            connection.execute(
                "INSERT INTO standard_specifications VALUES (?,?,?,?)",
                (item, scope, "original-geometry", value),
            )
        connection.execute("INSERT INTO series_counters VALUES ('S',4)")
        # Existing engineering references must survive ownership migration intact.
        file_id, dataset_id = str(uuid4()), str(uuid4())
        connection.execute(
            "INSERT INTO files VALUES (?, ?, 10, 'application/octet-stream', 'part.FCStd', 'immutable-key', ?, 'before')",
            (file_id, "a" * 64, creator),
        )
        connection.execute(
            "INSERT INTO datasets VALUES (?, ?, 'native', 'Original CAD', ?, 'before')",
            (dataset_id, items[0][1], creator),
        )
        connection.execute("INSERT INTO dataset_files VALUES (?,?,0)", (dataset_id, file_id))
        connection.execute(
            "INSERT INTO bom_lines VALUES (?,?,?,'2',1,?,'before')",
            (str(uuid4()), items[2][1], items[0][1], creator),
        )
        connection.execute(
            "INSERT INTO checkouts(id,revision_id,user_id,acquired_at,expires_at) VALUES (?,?,?,'before','later')",
            (str(uuid4()), items[0][1], creator),
        )
        preserved_tables = ("files", "datasets", "dataset_files", "bom_lines", "checkouts")
        before_references = {
            table: [tuple(r) for r in connection.execute(f"SELECT * FROM {table} ORDER BY 1")]
            for table in preserved_tables
        }
        before_items = [tuple(r) for r in connection.execute("SELECT * FROM items ORDER BY id")]
        before_revisions = [
            tuple(r) for r in connection.execute("SELECT * FROM item_revisions ORDER BY id")
        ]
        before_specs = [
            tuple(r)
            for r in connection.execute(
                "SELECT item_id,geometry_json,specification_json FROM standard_specifications ORDER BY item_id"
            )
        ]
        connection.commit()
    database.initialize()
    database.initialize()
    with database.connection() as connection:
        for table, original in before_references.items():
            assert [
                tuple(r) for r in connection.execute(f"SELECT * FROM {table} ORDER BY 1")
            ] == original
        lib = connection.execute("SELECT * FROM projects WHERE is_standard_library=1").fetchone()
        assert lib["project_number"].startswith("LIB-STANDARD-")
        assert (
            connection.execute("SELECT name FROM projects WHERE id=?", (project,)).fetchone()[0]
            == "LIB-STANDARD"
        )
        assert [
            tuple(r) for r in connection.execute("SELECT * FROM items ORDER BY id")
        ] == before_items
        assert [
            tuple(r) for r in connection.execute("SELECT * FROM item_revisions ORDER BY id")
        ] == before_revisions
        assert [
            tuple(r)
            for r in connection.execute(
                "SELECT item_id,geometry_json,specification_json FROM standard_specifications ORDER BY item_id"
            )
        ] == before_specs
        assert {r[0] for r in connection.execute("SELECT project_id FROM project_items")} == {
            lib["id"]
        }
        assert (
            connection.execute(
                "SELECT role FROM project_memberships WHERE project_id=? AND user_id=?",
                (lib["id"], creator),
            ).fetchone()[0]
            == "editor"
        )
        assert (
            connection.execute(
                "SELECT role FROM project_memberships WHERE project_id=? AND user_id=?",
                (lib["id"], engineer),
            ).fetchone()[0]
            == "viewer"
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM standard_specifications WHERE specification_json='same-specification'"
            ).fetchone()[0]
            == 2
        )
        assert (
            connection.execute(
                "SELECT scope FROM standard_specifications WHERE specification_json='unique-specification'"
            ).fetchone()[0]
            == lib["id"]
        )
        assert (
            connection.execute(
                "SELECT next_value FROM series_counters WHERE series='S'"
            ).fetchone()[0]
            == 4
        )
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
