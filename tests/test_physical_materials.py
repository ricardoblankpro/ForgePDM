"""Physical catalog links freeze density, enforce permissions and validate mass."""

import hashlib
import io
import json
from decimal import Decimal
from uuid import uuid4
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest
from conftest import create_item

from forgepdm.application.checkins import CheckInService
from forgepdm.application.descriptions import DescriptionService
from forgepdm.application.physical_materials import PhysicalMaterialService
from forgepdm.domain.entities import Conflict, Forbidden, ItemKind, LifecycleState
from forgepdm.domain.physical_materials import native_uuid, snapshot
from forgepdm.infrastructure.storage import FileStorage


def physical(density="7800"):
    return snapshot(
        {
            "version": 1,
            "source_uuid": "06ae5c92-de7b-46c9-984d-4dd87964bc5c",
            "name": "Steel-C15",
            "density_kg_m3": density,
        }
    )


def services(b):
    return DescriptionService(b.database, b.authorization, b.revisions), PhysicalMaterialService(
        b.database, b.authorization, b.revisions
    )


def test_atomic_registration_and_frozen_assignments(backend):
    b = backend
    user = b.users["editor"]
    desc, links = services(b)
    m = b.items.create_item(
        kind=ItemKind.PART,
        number_series="M",
        name="BAR C15",
        description="BAR C15",
        created_by=user.id,
        physical_material=physical(),
    )
    p = create_item(b)
    assigned = desc.save(
        user,
        p.current_revision_id,
        "",
        m.current_revision_id,
        desc.read(user, p.current_revision_id)["token"],
    )
    assert assigned["physical_material"]["density_kg_m3"] == "7800"
    current = links.read(user, m.current_revision_id)
    links.save(user, m.current_revision_id, physical("7900"), current["token"])
    assert desc.read(user, p.current_revision_id)["physical_material"]["density_kg_m3"] == "7800"
    with pytest.raises(Conflict):
        links.save(user, m.current_revision_id, physical(), current["token"])
    with pytest.raises(Forbidden):
        links.save(
            b.users["viewer"],
            m.current_revision_id,
            physical(),
            links.read(user, m.current_revision_id)["token"],
        )
    b.revisions.check_in(user, p.current_revision_id)
    b.revisions.transition_lifecycle(user, p.current_revision_id, LifecycleState.RELEASED)
    new, _ = b.revisions.create_next_revision(user, p.id, "Update")
    assert desc.read(user, new.id)["physical_material"]["density_kg_m3"] == "7800"


@pytest.mark.parametrize("value", ["0", "-1", "NaN", "Infinity", "bad", "1000001"])
def test_invalid_density_rejected_without_consuming_item_number(backend, value):
    b = backend
    with pytest.raises(ValueError):
        b.items.create_item(
            kind=ItemKind.PART,
            number_series="M",
            name="Invalid",
            description="",
            created_by=b.users["editor"].id,
            physical_material={**physical(), "density_kg_m3": value},
        )
    with b.database.connection() as c:
        assert not c.execute("SELECT 1 FROM items WHERE number_series='M'").fetchone()


def test_native_mass_is_atomic_replayable_and_matches_native_uuid(backend):
    b = backend
    user = b.users["editor"]
    desc, links = services(b)
    binding = physical()
    m = b.items.create_item(
        kind=ItemKind.PART,
        number_series="M",
        name="BAR",
        description="BAR",
        created_by=user.id,
        physical_material=binding,
    )
    p = create_item(b)
    current = desc.read(user, p.current_revision_id)
    description = {
        "version": 2,
        "revision_id": p.current_revision_id,
        "description": "BAR",
        "material_revision_id": m.current_revision_id,
        "physical_material": binding,
        "expected_token": current["token"],
    }
    evidence = {
        "version": 1,
        "revision_id": p.current_revision_id,
        "physical_material": binding,
        "objects": [
            {"name": "Solid", "volume_mm3": "1000000", "native_uuid": native_uuid(binding)}
        ],
        "mass_kg": "7.8",
        "reason": "",
    }

    body_uuid = [native_uuid(binding)]

    def data():
        root = ET.Element("Document")
        objects = ET.SubElement(root, "ObjectData")
        meta = ET.SubElement(objects, "Object", name="ForgePDM_Metadata")
        props = ET.SubElement(meta, "Properties")
        for key, val in [("PDMDescriptionData", description), ("PDMPartPhysicalData", evidence)]:
            ET.SubElement(
                ET.SubElement(props, "Property", name=key), "String", value=json.dumps(val)
            )
        solid = ET.SubElement(objects, "Object", name="Solid")
        props = ET.SubElement(solid, "Properties")
        ET.SubElement(
            ET.SubElement(props, "Property", name="ShapeMaterial"),
            "PropertyMaterial",
            uuid=body_uuid[0],
        )
        stream = io.BytesIO()
        with ZipFile(stream, "w") as archive:
            archive.writestr("Document.xml", ET.tostring(root))
        return stream.getvalue()

    checkout = b.revisions.current_checkout(user, p.current_revision_id)
    args = {
        "user": user,
        "revision_id": p.current_revision_id,
        "operation_id": str(uuid4()),
        "expected_checkout_id": checkout.id,
        "expected_checkout_version": checkout.version,
        "filename": "part.FCStd",
        "media_type": "application/octet-stream",
    }
    checkins = CheckInService(
        b.database,
        FileStorage(b.storage.root, max_upload_bytes=1000000),
        b.authorization,
        b.revisions,
    )
    evidence["mass_kg"] = "99"
    payload = data()
    with pytest.raises(ValueError):
        checkins.check_in(
            **args,
            content_hash=hashlib.sha256(payload).hexdigest(),
            byte_size=len(payload),
            source=io.BytesIO(payload),
        )
    assert desc.read(user, p.current_revision_id)["physical_material"] is None
    evidence["mass_kg"] = "7.8"
    body_uuid[0] = str(uuid4())
    payload = data()
    with pytest.raises(Conflict):
        checkins.check_in(
            **args,
            content_hash=hashlib.sha256(payload).hexdigest(),
            byte_size=len(payload),
            source=io.BytesIO(payload),
        )
    body_uuid[0] = native_uuid(binding)
    payload = data()
    args.update(content_hash=hashlib.sha256(payload).hexdigest(), byte_size=len(payload))
    result = checkins.check_in(**args, source=io.BytesIO(payload))
    assert checkins.check_in(**args, source=io.BytesIO(payload)) == result
    assert Decimal(links.mass(user, p.current_revision_id)["mass_kg"]) == Decimal("7.8")
    assert links.mass(user, p.current_revision_id)["content_hash"] == args["content_hash"]
    other = b.items.create_item(
        kind=ItemKind.PART,
        number_series="M",
        name="Different stock",
        description="Different stock",
        created_by=user.id,
        physical_material=binding,
    )
    b.revisions.acquire_checkout(user, p.current_revision_id)
    desc.save(
        user,
        p.current_revision_id,
        "",
        other.current_revision_id,
        desc.read(user, p.current_revision_id)["token"],
    )
    assert links.mass(user, p.current_revision_id)["mass_kg"] is None


def test_physical_link_api_requires_curator_checkout_and_released_is_immutable(
    backend, monkeypatch, tmp_path
):
    from conftest import TEST_PASSWORD
    from fastapi.testclient import TestClient

    from forgepdm.main import create_app

    b = backend
    user = b.users["editor"]
    monkeypatch.setenv("FORGEPDM_FILE_ROOT", str(tmp_path / "api-files"))
    with TestClient(create_app(b.database.path)) as client:
        headers = {
            "Authorization": "Bearer "
            + client.post(
                "/api/v1/auth/login", json={"username": "editor", "password": TEST_PASSWORD}
            ).json()["access_token"]
        }
        created = client.post(
            "/api/v1/items",
            headers=headers,
            json={
                "kind": "part",
                "number_series": "M",
                "name": "C15 BAR",
                "description": "C15 BAR",
                "physical_material": physical(),
            },
        )
        assert created.status_code == 201
        revision = created.json()["current_revision_id"]
        path = f"/api/v1/revisions/{revision}/physical-material"
        link = client.get(path, headers=headers).json()
        assert link["physical_material"]["density_kg_m3"] == "7800"
        bad = client.put(
            path,
            headers=headers,
            json={
                "physical_material": {**physical(), "density_kg_m3": "NaN"},
                "expected_token": link["token"],
            },
        )
        assert bad.status_code == 422
        b.revisions.check_in(user, revision)
        b.revisions.transition_lifecycle(user, revision, LifecycleState.RELEASED)
        assert (
            client.put(
                path,
                headers=headers,
                json={"physical_material": physical("7900"), "expected_token": link["token"]},
            ).status_code
            == 409
        )
        assert client.get(path).status_code == 401
        p = create_item(b)
        mass = client.get(f"/api/v1/revisions/{p.current_revision_id}/mass", headers=headers).json()
        assert mass["mass_kg"] is None


def test_migration_15_preserves_description_only_assignments(backend):
    from forgepdm.application.descriptions import DescriptionService

    b = backend
    user = b.users["editor"]
    desc = DescriptionService(b.database, b.authorization, b.revisions)
    m = b.items.create_item(
        kind=ItemKind.PART,
        number_series="M",
        name="Old material",
        description="Old material",
        created_by=user.id,
    )
    p = create_item(b)
    before = desc.save(
        user,
        p.current_revision_id,
        "",
        m.current_revision_id,
        desc.read(user, p.current_revision_id)["token"],
    )
    with b.database.transaction() as c:
        c.execute("DROP TABLE dataset_part_mass")
        c.execute("DROP TABLE part_physical_assignments")
        c.execute("DROP TABLE material_physical_links")
        c.execute("DELETE FROM schema_version WHERE version=15")
    b.database.initialize()
    b.database.initialize()
    assert desc.read(user, p.current_revision_id) == before
    assert desc.read(user, p.current_revision_id)["physical_material"] is None
