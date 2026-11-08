"""Description-only materials and revision-safe CAD publication."""

import hashlib
import io
import json
from uuid import uuid4
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest
from conftest import create_item

from forgepdm.application.checkins import CheckInService
from forgepdm.application.descriptions import DescriptionService
from forgepdm.domain.entities import Conflict, Forbidden, ItemKind, LifecycleState
from forgepdm.infrastructure.storage import FileStorage


def service(b):
    return DescriptionService(b.database, b.authorization, b.revisions)


def material(b):
    return b.items.create_item(
        kind=ItemKind.PART,
        number_series="M",
        name="STEEL PLATE 6 MM",
        description="STEEL PLATE 6 MM",
        created_by=b.users["editor"].id,
    )


def test_description_only_material_and_part_pin(backend):
    b = backend
    svc = service(b)
    user = b.users["editor"]
    m = material(b)
    p = create_item(b)
    assert svc.read(user, m.current_revision_id)["description"] == "STEEL PLATE 6 MM"
    b.revisions.check_in(user, m.current_revision_id)
    b.revisions.transition_lifecycle(user, m.current_revision_id, LifecycleState.RELEASED)
    current = svc.read(user, p.current_revision_id)
    assigned = svc.save(user, p.current_revision_id, "", m.current_revision_id, current["token"])
    assert assigned["description"] == "STEEL PLATE 6 MM"
    with pytest.raises(Conflict):
        svc.save(user, p.current_revision_id, "", None, current["token"])
    b.revisions.check_in(user, p.current_revision_id)
    b.revisions.transition_lifecycle(user, p.current_revision_id, LifecycleState.RELEASED)
    with pytest.raises(Conflict):
        svc.save(user, p.current_revision_id, "", None, assigned["token"])
    revision, _ = b.revisions.create_next_revision(user, p.id, "Update")
    assert svc.read(user, revision.id)["material_revision_id"] == m.current_revision_id
    svc.save(user, revision.id, "", None, svc.read(user, revision.id)["token"])
    assert svc.read(user, p.current_revision_id)["description"] == assigned["description"]


def test_assembly_free_text_and_material_only_part_selection(backend):
    b = backend
    svc = service(b)
    user = b.users["editor"]
    a = create_item(b, kind="assembly")
    p = create_item(b)
    m = material(b)
    result = svc.save(
        user,
        a.current_revision_id,
        " General mounting ",
        None,
        svc.read(user, a.current_revision_id)["token"],
    )
    assert result["description"] == "General mounting"
    with pytest.raises(ValueError):
        svc.save(user, a.current_revision_id, "", m.current_revision_id, result["token"])
    with pytest.raises(Conflict):
        svc.save(
            user,
            p.current_revision_id,
            "",
            a.current_revision_id,
            svc.read(user, p.current_revision_id)["token"],
        )
    with pytest.raises(Forbidden):
        svc.save(b.users["viewer"], a.current_revision_id, "Changed", None, result["token"])


def native(value):
    root = ET.Element("Document")
    obj = ET.SubElement(ET.SubElement(root, "ObjectData"), "Object", name="ForgePDM_Metadata")
    props = ET.SubElement(obj, "Properties")
    ET.SubElement(
        ET.SubElement(props, "Property", name="PDMDescriptionData"),
        "String",
        value=json.dumps(value),
    )
    stream = io.BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr("Document.xml", ET.tostring(root))
    return stream.getvalue()


def test_atomic_description_conflict_and_replay(backend):
    b = backend
    svc = service(b)
    user = b.users["editor"]
    a = create_item(b, kind="assembly")
    initial = svc.read(user, a.current_revision_id)
    value = {
        "version": 1,
        "revision_id": a.current_revision_id,
        "expected_token": initial["token"],
        "description": "General mounting",
        "material_revision_id": None,
    }
    svc.save(user, a.current_revision_id, "Web edit", None, initial["token"])
    data = native(value)
    checkout = b.revisions.current_checkout(user, a.current_revision_id)
    args = {
        "user": user,
        "revision_id": a.current_revision_id,
        "operation_id": str(uuid4()),
        "expected_checkout_id": checkout.id,
        "expected_checkout_version": checkout.version,
        "content_hash": hashlib.sha256(data).hexdigest(),
        "byte_size": len(data),
        "filename": "assembly.FCStd",
        "media_type": "application/octet-stream",
    }
    checkins = CheckInService(
        b.database,
        FileStorage(b.storage.root, max_upload_bytes=1000000),
        b.authorization,
        b.revisions,
    )
    with pytest.raises(Conflict):
        checkins.check_in(**args, source=io.BytesIO(data))
    with b.database.connection() as c:
        assert c.execute("SELECT count(*) FROM datasets").fetchone()[0] == 0
    value["expected_token"] = svc.read(user, a.current_revision_id)["token"]
    data = native(value)
    args.update(content_hash=hashlib.sha256(data).hexdigest(), byte_size=len(data))
    result = checkins.check_in(**args, source=io.BytesIO(data))
    assert svc.read(user, a.current_revision_id)["description"] == "General mounting"
    assert checkins.check_in(**args, source=io.BytesIO(data)) == result
    with b.database.connection() as c:
        assert c.execute("SELECT count(*) FROM dataset_descriptions").fetchone()[0] == 1


def test_tree_status_uses_exact_revision_description(backend):
    from forgepdm.application.tree_status import TreeStatusService

    b = backend
    svc = service(b)
    user = b.users["editor"]
    a = create_item(b, kind="assembly")
    svc.save(
        user,
        a.current_revision_id,
        "Original",
        None,
        svc.read(user, a.current_revision_id)["token"],
    )
    b.revisions.check_in(user, a.current_revision_id)
    b.revisions.transition_lifecycle(user, a.current_revision_id, LifecycleState.RELEASED)
    revision, _ = b.revisions.create_next_revision(user, a.id, "New")
    svc.save(user, revision.id, "New mounting", None, svc.read(user, revision.id)["token"])
    rows = TreeStatusService(b.database, b.authorization).revisions(
        user, [a.current_revision_id, revision.id]
    )["items"]
    assert [r["description"] for r in rows] == ["Original", "New mounting"]


def test_description_api_and_catalog_metadata(backend, monkeypatch, tmp_path):
    from conftest import TEST_PASSWORD
    from fastapi.testclient import TestClient

    from forgepdm.main import create_app

    b = backend
    m = material(b)
    a = create_item(b, kind="assembly")
    monkeypatch.setenv("FORGEPDM_FILE_ROOT", str(tmp_path / "api-files"))
    with TestClient(create_app(b.database.path)) as client:
        login = client.post(
            "/api/v1/auth/login", json={"username": "editor", "password": TEST_PASSWORD}
        )
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        url = f"/api/v1/revisions/{a.current_revision_id}/description"
        current = client.get(url, headers=headers).json()
        updated = client.put(
            url,
            headers=headers,
            json={"description": "General mounting", "expected_token": current["token"]},
        )
        assert updated.status_code == 200
        detail = client.get(f"/api/v1/revisions/{a.current_revision_id}", headers=headers).json()
        assert detail["description_record"]["description"] == "General mounting"
        assert (
            client.put(
                url,
                headers=headers,
                json={"description": "Conflict", "expected_token": current["token"]},
            ).status_code
            == 409
        )
        assert client.get(url).status_code == 401
        murl = f"/api/v1/revisions/{m.current_revision_id}/description"
        current = client.get(murl, headers=headers).json()
        assert (
            client.put(
                murl,
                headers=headers,
                json={"description": "STEEL PLATE 8 MM", "expected_token": current["token"]},
            ).status_code
            == 200
        )
        catalog = client.get("/api/v1/items?number_series=M", headers=headers).json()["items"]
        assert catalog[0]["description"] == "STEEL PLATE 8 MM"


def test_migration_14_preserves_legacy_records_and_seeds_only_materials(backend):
    b = backend
    m = material(b)
    p = create_item(b)
    with b.database.transaction() as c:
        c.execute(
            "INSERT INTO revision_material_data VALUES (?,?)",
            (
                m.current_revision_id,
                json.dumps({"description": "LEGACY MATERIAL DESCRIPTION", "density_kg_m3": "7850"}),
            ),
        )
        c.execute("DROP TABLE dataset_descriptions")
        c.execute("DROP TABLE revision_descriptions")
        c.execute("DELETE FROM schema_version WHERE version=14")
        old_items = [tuple(row) for row in c.execute("SELECT * FROM items ORDER BY id")]
        old_specs = [
            tuple(row)
            for row in c.execute("SELECT * FROM revision_material_data ORDER BY revision_id")
        ]
    b.database.initialize()
    b.database.initialize()
    assert (
        service(b).read(b.users["editor"], m.current_revision_id)["description"]
        == "LEGACY MATERIAL DESCRIPTION"
    )
    assert service(b).read(b.users["editor"], p.current_revision_id)["description"] == ""
    with b.database.connection() as c:
        assert old_items == [tuple(row) for row in c.execute("SELECT * FROM items ORDER BY id")]
        assert old_specs == [
            tuple(row)
            for row in c.execute("SELECT * FROM revision_material_data ORDER BY revision_id")
        ]
        assert not c.execute("PRAGMA foreign_key_check").fetchall()
