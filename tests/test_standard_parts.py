"""Specification identity, snapshot evidence and numbering regression coverage."""

import io
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from xml.etree.ElementTree import Element, SubElement, tostring
from zipfile import ZipFile

import pytest

from forgepdm.application.catalog import CatalogService
from forgepdm.application.standard_parts import StandardPartsService, read_occurrences
from forgepdm.domain.entities import Conflict, DatasetType, ItemKind
from forgepdm.domain.standard_parts import encode, specification

GEOMETRY = {"Type": "ISO4017", "Diameter": "M8", "Length": "25", "LeftHanded": False}
SPEC = specification(dict(geometry=GEOMETRY, material="steel", grade="8.8", finish="zinc"))


def register(backend, spec=SPEC, **kwargs):
    return backend.items.create_item(
        kind=ItemKind.PART,
        number_series="S",
        name="Bolt",
        description="",
        created_by=backend.users["editor"].id,
        project_id=backend.project_id,
        standard_specification=spec,
        **kwargs,
    )


def native(revision, *, geometry=None, repeated=False):
    root = Element("Document")
    SubElement(root, "Objects")
    objects = SubElement(root, "ObjectData")
    identifier = str(uuid4())
    for name in ["Bolt", "CopiedBolt"] if repeated else ["Bolt"]:
        obj = SubElement(objects, "Object", name=name)
        props = SubElement(obj, "Properties")
        proxy = SubElement(props, "Property", name="Proxy")
        SubElement(proxy, "Python", module="FastenersCmd", **{"class": "FSScrewObject"})
        for key, value in SPEC["geometry"].items():
            prop = SubElement(props, "Property", name=key, type="App::PropertyString")
            SubElement(prop, "String", value=value)
        prop = SubElement(props, "Property", name="PDMStandardAssociation")
        SubElement(
            prop,
            "String",
            value=encode(
                dict(
                    version=1,
                    occurrence_id=identifier,
                    revision_id=revision,
                    geometry=geometry or SPEC["geometry"],
                )
            ),
        )
    stream = io.BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr("Document.xml", tostring(root))
    return stream.getvalue()


def test_matching_normalizes_and_preserves_purchasing_distinctions(backend):
    first = register(backend)
    other = register(backend, dict(SPEC, grade="10.9"))
    service = StandardPartsService(backend.database, backend.authorization)
    result = service.match(backend.users["viewer"], GEOMETRY)["items"]
    assert {row["id"] for row in result} == {first.id, other.id}
    with pytest.raises(Conflict):
        register(backend)
    assert len(service.match(backend.users["viewer"], dict(GEOMETRY, Length="30"))["items"]) == 0
    with backend.database.transaction() as connection:
        connection.execute(
            "DELETE FROM project_memberships WHERE user_id=?", (backend.users["viewer"].id,)
        )
    assert service.match(backend.users["viewer"], GEOMETRY)["items"] == []


def test_series_filter_and_concurrent_allocation(backend):
    def create(index):
        return backend.items.create_item(
            kind=ItemKind.PART,
            number_series="S",
            name=str(index),
            description="",
            created_by=backend.users["editor"].id,
            project_id=backend.project_id,
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        items = list(pool.map(create, range(12)))
    assert len({item.number for item in items}) == 12
    backend.items.create_item(
        kind=ItemKind.PART, name="Engineered", description="", created_by=backend.users["admin"].id
    )
    catalog = CatalogService(backend.database, backend.authorization)
    page = catalog.search_items(backend.users["admin"], number_series="S")
    assert len(page["items"]) == 12
    assert all(item["number_series"] == "S" for item in page["items"])


def test_metadata_only_revision_can_be_checked_in_and_released(backend):
    from forgepdm.domain.entities import LifecycleState

    item = register(backend)
    backend.revisions.check_in(backend.users["editor"], item.current_revision_id)
    backend.revisions.transition_lifecycle(
        backend.users["editor"], item.current_revision_id, LifecycleState.RELEASED
    )
    assert backend.items.get_item(item.id)[1].lifecycle_state == LifecycleState.RELEASED


def test_native_occurrences_are_validated_and_published_with_dataset(backend):
    item = register(backend)
    parent = backend.items.create_item(
        kind=ItemKind.ASSEMBLY,
        name="Assembly",
        description="",
        created_by=backend.users["editor"].id,
        project_id=backend.project_id,
    )
    backend.storage.max_upload_bytes = 100000
    dataset, _ = backend.datasets.attach_file(
        user=backend.users["editor"],
        revision_id=parent.current_revision_id,
        dataset_type=DatasetType.NATIVE_CAD,
        dataset_name="Native",
        filename="assembly.FCStd",
        media_type="application/zip",
        source=io.BytesIO(native(item.current_revision_id)),
    )
    with backend.database.connection() as connection:
        rows = connection.execute(
            "SELECT * FROM dataset_standard_occurrences WHERE dataset_id=?", (dataset.id,)
        ).fetchall()
    assert len(rows) == 1 and rows[0]["revision_id"] == item.current_revision_id
    with pytest.raises(Conflict):
        backend.datasets.attach_file(
            user=backend.users["editor"],
            revision_id=parent.current_revision_id,
            dataset_type=DatasetType.NATIVE_CAD,
            dataset_name="Native",
            filename="bad.FCStd",
            media_type="application/zip",
            source=io.BytesIO(
                native(item.current_revision_id, geometry=dict(SPEC["geometry"], Length="30"))
            ),
        )
    with pytest.raises(ValueError, match="Duplicate"):
        read_occurrences(io.BytesIO(native(item.current_revision_id, repeated=True)))


def test_atomic_checkin_evidence_and_replay(backend):
    import hashlib

    from forgepdm.application.checkins import CheckInService

    item = register(backend)
    parent = backend.items.create_item(
        kind=ItemKind.ASSEMBLY,
        name="Assembly",
        description="",
        created_by=backend.users["editor"].id,
        project_id=backend.project_id,
    )
    backend.storage.max_upload_bytes = 100000
    lease = backend.revisions.current_checkout(backend.users["editor"], parent.current_revision_id)
    service = CheckInService(
        backend.database, backend.storage, backend.authorization, backend.revisions
    )
    content = native(item.current_revision_id)
    args = dict(
        user=backend.users["editor"],
        revision_id=parent.current_revision_id,
        operation_id=str(uuid4()),
        expected_checkout_id=lease.id,
        expected_checkout_version=lease.version,
        content_hash=hashlib.sha256(content).hexdigest(),
        byte_size=len(content),
        filename="assembly.FCStd",
        media_type="application/zip",
    )
    first = service.check_in(**args, source=io.BytesIO(content))
    assert service.check_in(**args, source=io.BytesIO(content)) == first
    with backend.database.connection() as connection:
        assert (
            connection.execute("SELECT count(*) FROM dataset_standard_occurrences").fetchone()[0]
            == 1
        )


def test_preupgrade_migration_preserves_counters_and_identifiers(tmp_path):
    from forgepdm.infrastructure.database import MIGRATIONS, Database

    database = Database(tmp_path / "old.sqlite3")
    with database.connect() as connection:
        connection.execute(
            "CREATE TABLE schema_version(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        for version, sql in MIGRATIONS:
            if version >= 10:
                break
            connection.executescript(sql)
            connection.execute("INSERT INTO schema_version VALUES (?, 'before')", (version,))
        connection.execute("INSERT INTO number_counters VALUES ('part', 42)")
        connection.execute("INSERT INTO number_counters VALUES ('assembly', 17)")
        connection.execute("BEGIN")
        connection.execute(
            "INSERT INTO users(id,username,display_name,enabled,created_at) VALUES ('old-user','old','Old',1,'before')"
        )
        for kind, number, item_id, revision_id in [
            ("part", "P000041", "old-part", "old-part-rev"),
            ("assembly", "A000016", "old-assembly", "old-assembly-rev"),
        ]:
            connection.execute(
                "INSERT INTO items(id,number,kind,name,created_by,created_at,current_revision_id) VALUES (?,?,?,?,?,?,?)",
                (item_id, number, kind, "Old item", "old-user", "before", revision_id),
            )
            connection.execute(
                "INSERT INTO item_revisions(id,item_id,label,sequence,lifecycle_state,created_by,created_at) VALUES (?,?,'A',1,'working','old-user','before')",
                (revision_id, item_id),
            )
        connection.execute(
            "INSERT INTO bom_lines VALUES ('old-line','old-assembly-rev','old-part-rev','2',1,'old-user','before')"
        )
        before = [tuple(row) for row in connection.execute("SELECT * FROM bom_lines")]
        connection.commit()
    database.initialize()
    database.initialize()
    with database.connection() as connection:
        assert [tuple(row) for row in connection.execute("SELECT * FROM bom_lines")] == before
        assert {
            row["number"]: row["number_series"] for row in connection.execute("SELECT * FROM items")
        } == {"P000041": "P", "A000016": "A"}
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
        assert dict(connection.execute("SELECT series,next_value FROM series_counters")) == {
            "P": 42,
            "A": 17,
        }
        assert dict(connection.execute("SELECT item_kind,next_value FROM number_counters")) == {
            "part": 42,
            "assembly": 17,
        }


def test_standard_api_permissions_and_conflicts(backend, tmp_path, monkeypatch):
    from conftest import TEST_PASSWORD
    from fastapi.testclient import TestClient

    monkeypatch.setenv("FORGEPDM_DATABASE", str(tmp_path / "default.sqlite3"))
    monkeypatch.setenv("FORGEPDM_FILE_ROOT", str(tmp_path / "http-files"))
    from forgepdm.main import create_app

    app = create_app(backend.database.path)
    with TestClient(app) as client:

        def login(name):
            response = client.post(
                "/api/v1/auth/login", json={"username": name, "password": TEST_PASSWORD}
            )
            return {"Authorization": "Bearer " + response.json()["access_token"]}

        editor, viewer = login("editor"), login("viewer")
        assert client.get("/api/v1/standard-parts/capabilities").status_code == 401
        assert (
            client.get("/api/v1/standard-parts/capabilities", headers=editor).json()["version"] == 1
        )
        payload = dict(
            kind="part",
            number_series="S",
            name="Bolt",
            project_id=backend.project_id,
            standard_specification=SPEC,
        )
        assert client.post("/api/v1/items", json=payload, headers=viewer).status_code == 403
        response = client.post("/api/v1/items", json=payload, headers=editor)
        assert response.status_code == 201
        item = response.json()
        assert item["number"] == "S000001" and item["number_series"] == "S"
        assert (
            client.get("/api/v1/items/" + item["id"], headers=viewer).json()[
                "standard_specification"
            ]
            == SPEC
        )
        assert client.post("/api/v1/items", json=payload, headers=editor).status_code == 409
        assert (
            client.post(
                "/api/v1/items", json=dict(payload, kind="assembly"), headers=editor
            ).status_code
            == 422
        )
        page = client.get("/api/v1/items?number_series=S", headers=viewer).json()
        assert len(page["items"]) == 1 and page["items"][0]["number_series"] == "S"
        assert client.get("/api/v1/items?number_series=Z", headers=viewer).status_code == 422
        matches = client.post("/api/v1/standard-parts/matches", json=GEOMETRY, headers=viewer)
        assert len(matches.json()["items"]) == 1
        assert (
            client.post(
                "/api/v1/standard-parts/matches",
                json={"Type": {"nested": "invalid"}},
                headers=viewer,
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/v1/standard-parts/matches",
                json={"Type": "ISO4017", "Length": "1e100000"},
                headers=viewer,
            ).status_code
            == 422
        )


def test_concurrent_specification_registration_has_one_winner(backend):
    def create(_):
        try:
            return register(backend).id
        except Conflict:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(create, range(4)))
    assert sum(result is not None for result in results) == 1


def test_client_and_server_specification_contracts_stay_identical():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    assert (root / "src/forgepdm/domain/standard_parts.py").read_text() == (
        root / "clients/freecad/freecad/forgepdm/standard_contract.py"
    ).read_text()
