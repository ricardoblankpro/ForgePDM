import pytest
from conftest import create_item

from forgepdm.application.materials import MaterialService, token
from forgepdm.domain.entities import Conflict, Forbidden, ItemKind, LifecycleState


def service(b):
    return MaterialService(b.database, b.authorization, b.revisions)


def material(b, name="Stock"):
    item = b.items.create_item(
        kind=ItemKind.PART,
        number_series="M",
        name=name,
        description="",
        created_by=b.users["editor"].id,
    )
    spec = {
        "grade": "s235",
        "standard": "en10025",
        "form": "bar",
        "dimensions": {"diameter": "20"},
        "base_uom": "m",
        "density_kg_m3": "7850",
    }
    service(b).save_specification(b.users["editor"], item.current_revision_id, spec, token({}))
    b.revisions.check_in(b.users["editor"], item.current_revision_id)
    b.revisions.transition_lifecycle(
        b.users["editor"], item.current_revision_id, LifecycleState.RELEASED
    )
    return item


def test_material_identity_units_and_revision_pins(backend):
    b = backend
    m = material(b)
    assert m.number == "M000001"
    p = create_item(b)
    svc = service(b)
    before = svc.read(b.users["editor"], p.current_revision_id)
    line = {"component_revision_id": m.current_revision_id, "quantity": "400", "uom": "mm"}
    result = svc.replace(
        b.users["editor"], p.current_revision_id, [line], before["token"], "complete"
    )
    with pytest.raises(Conflict):
        svc.replace(b.users["editor"], p.current_revision_id, [], before["token"])
    b.revisions.check_in(b.users["editor"], p.current_revision_id)
    b.revisions.transition_lifecycle(
        b.users["editor"], p.current_revision_id, LifecycleState.RELEASED
    )
    report = svc.calculate(
        b.users["editor"],
        [{"root_revision_id": p.current_revision_id, "quantity": "6"}],
        True,
        True,
    )
    assert report["totals"] == [{"item_code": "M000001", "uom": "m", "quantity": "2.400"}]
    assert svc.snapshot(b.users["viewer"], report["id"]) == report
    revision, _ = b.revisions.create_next_revision(b.users["editor"], p.id, "Updated")
    copied = svc.read(b.users["editor"], revision.id)
    assert copied["readiness"] == "unreviewed"
    assert copied["lines"] == result["lines"]


def test_duplicate_identity_and_permissions(backend):
    b = backend
    m = material(b)
    second = b.items.create_item(
        kind=ItemKind.PART,
        number_series="M",
        name="Duplicate",
        description="",
        created_by=b.users["editor"].id,
    )
    spec = service(b).specification(b.users["editor"], m.current_revision_id)["specification"]
    with pytest.raises(Conflict, match="already exists"):
        service(b).save_specification(
            b.users["editor"], second.current_revision_id, spec, token({})
        )
    with pytest.raises(Forbidden):
        b.items.create_item(
            kind=ItemKind.PART,
            number_series="M",
            name="Denied",
            description="",
            created_by=b.users["viewer"].id,
        )


def test_incomplete_requirements_and_unit_rejection(backend):
    b = backend
    p = create_item(b)
    svc = service(b)
    with pytest.raises(Conflict, match="not purchasing-ready"):
        svc.calculate(
            b.users["editor"], [{"root_revision_id": p.current_revision_id, "quantity": "1"}], True
        )
    m = material(b)
    with pytest.raises(ValueError, match="dimension"):
        svc.replace(
            b.users["editor"],
            p.current_revision_id,
            [{"component_revision_id": m.current_revision_id, "quantity": "1", "uom": "kg"}],
            svc.read(b.users["editor"], p.current_revision_id)["token"],
        )


def test_nested_assemblies_additional_inputs_and_where_used(backend):
    b = backend
    m = material(b)
    svc = service(b)
    p = create_item(b)
    sub = create_item(b, kind="assembly")
    top = create_item(b, kind="assembly")
    user = b.users["editor"]
    for item, qty in [(p, "400"), (sub, "100")]:
        current = svc.read(user, item.current_revision_id)
        svc.replace(
            user,
            item.current_revision_id,
            [{"component_revision_id": m.current_revision_id, "quantity": qty, "uom": "mm"}],
            current["token"],
            "complete",
        )
    b.bom.replace_bom(
        user,
        sub.current_revision_id,
        [{"component_revision_id": p.current_revision_id, "quantity": "3", "position": 1}],
    )
    b.bom.replace_bom(
        user,
        top.current_revision_id,
        [{"component_revision_id": sub.current_revision_id, "quantity": "2", "position": 1}],
    )
    report = svc.calculate(
        user,
        [
            {
                "root_revision_id": top.current_revision_id,
                "quantity": "2",
                "project_context": b.project_id,
            }
        ],
    )
    assert report["totals"][0]["quantity"] == "5.200"
    assert len(report["lines"]) == 2
    assert len(report["lines"][1]["path"]) == 4
    assert report["issues"]


def test_migration_13_preserves_12_rows_and_counters(backend, tmp_path):
    from forgepdm.infrastructure.database import MIGRATIONS, Database

    database = Database(tmp_path / "pre13.sqlite3")
    with database.connection() as c:
        for version, sql in MIGRATIONS:
            if version >= 13:
                break
            c.executescript(sql)
            c.execute("INSERT INTO schema_version VALUES (?,'before')", (version,))
        c.execute("UPDATE series_counters SET next_value=42")
        old_counters = [tuple(row) for row in c.execute("SELECT * FROM series_counters")]
        old_library = dict(
            c.execute("SELECT * FROM projects WHERE is_standard_library=1").fetchone()
        )
    database.initialize()
    database.initialize()
    with database.connection() as c:
        assert [tuple(row) for row in c.execute("SELECT * FROM series_counters")] == old_counters
        library = dict(c.execute("SELECT * FROM projects WHERE is_standard_library=1").fetchone())
        assert library["id"] == old_library["id"]
        assert not c.execute("PRAGMA foreign_key_check").fetchall()
        assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert "'M'" in c.execute("SELECT sql FROM sqlite_master WHERE name='items'").fetchone()[0]


def test_native_material_upload_is_atomic_and_replayable(backend):
    import hashlib
    import io
    from uuid import uuid4
    from xml.etree import ElementTree as ET
    from zipfile import ZipFile

    from forgepdm.application.checkins import CheckInService
    from forgepdm.infrastructure.storage import FileStorage

    b = backend
    m = material(b)
    p = create_item(b)
    user = b.users["editor"]
    svc = service(b)
    evidence = {
        "version": 1,
        "revision_id": p.current_revision_id,
        "expected_token": svc.read(user, p.current_revision_id)["token"],
        "lines": [{"component_revision_id": m.current_revision_id, "quantity": "400", "uom": "mm"}],
        "mass_evidence": [],
    }
    root = ET.Element("Document")
    obj = ET.SubElement(ET.SubElement(root, "ObjectData"), "Object", name="ForgePDM_Metadata")
    props = ET.SubElement(obj, "Properties")
    import json

    ET.SubElement(
        ET.SubElement(props, "Property", name="PDMMaterialInputs"),
        "String",
        value=json.dumps(evidence),
    )
    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("Document.xml", ET.tostring(root))
    data = output.getvalue()
    checkout = b.revisions.current_checkout(user, p.current_revision_id)
    args = {
        "user": user,
        "revision_id": p.current_revision_id,
        "operation_id": str(uuid4()),
        "expected_checkout_id": checkout.id,
        "expected_checkout_version": checkout.version,
        "content_hash": hashlib.sha256(data).hexdigest(),
        "byte_size": len(data),
        "filename": "model.FCStd",
        "media_type": "application/octet-stream",
    }
    checkins = CheckInService(
        b.database,
        FileStorage(b.storage.root, max_upload_bytes=1000000),
        b.authorization,
        b.revisions,
    )
    result = checkins.check_in(**args, source=io.BytesIO(data))
    assert svc.read(user, p.current_revision_id)["lines"][0]["quantity"] == "400"
    assert checkins.check_in(**args, source=io.BytesIO(data)) == result
    with b.database.connection() as c:
        assert c.execute("SELECT count(*) FROM dataset_material_evidence").fetchone()[0] == 1


def test_explicit_conversion_and_source_properties(backend):
    b = backend
    m = material(b)
    user = b.users["editor"]
    svc = service(b)
    revision, _ = b.revisions.create_next_revision(user, m.id, "Conversion evidence")
    spec = svc.specification(user, revision.id)
    spec["specification"]["uom_conversions"] = {"kg": "0.2"}
    svc.save_specification(user, revision.id, spec["specification"], spec["token"])
    b.revisions.check_in(user, revision.id)
    b.revisions.transition_lifecycle(user, revision.id, LifecycleState.RELEASED)
    p = create_item(b)
    svc.save_properties(
        user,
        p.current_revision_id,
        {
            "description": "Steel shaft",
            "classification": "SHAFT",
            "attributes": {"heat_treated": False},
        },
        token({}),
    )
    svc.replace(
        user,
        p.current_revision_id,
        [{"component_revision_id": revision.id, "quantity": "1000", "uom": "g"}],
        svc.read(user, p.current_revision_id)["token"],
        "complete",
    )
    report = svc.calculate(user, [{"root_revision_id": p.current_revision_id, "quantity": "2"}])
    assert report["totals"][0]["quantity"] == "0.4000"
    assert (
        report["sources"][p.current_revision_id]["engineering_properties"]["classification"]
        == "SHAFT"
    )


def test_material_counter_exhaustion_rolls_back(backend):
    b = backend
    material(b)
    with b.database.transaction() as c:
        c.execute("UPDATE series_counters SET next_value=1000000 WHERE series='M'")
    with pytest.raises(Conflict, match="exhausted"):
        b.items.create_item(
            kind=ItemKind.PART,
            number_series="M",
            name="Overflow",
            description="",
            created_by=b.users["editor"].id,
        )
    with b.database.connection() as c:
        assert c.execute("SELECT count(*) FROM items WHERE number_series='M'").fetchone()[0] == 1


def test_material_api_and_authorized_exports(backend, monkeypatch, tmp_path):
    from conftest import TEST_PASSWORD
    from fastapi.testclient import TestClient

    from forgepdm.main import create_app

    b = backend
    m = material(b)
    p = create_item(b)
    monkeypatch.setenv("FORGEPDM_FILE_ROOT", str(tmp_path / "api-files"))
    app = create_app(b.database.path)
    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login", json={"username": "editor", "password": TEST_PASSWORD}
        )
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        base = f"/api/v1/revisions/{p.current_revision_id}"
        current = client.get(base + "/material-bom", headers=headers).json()
        changed = client.put(
            base + "/material-bom",
            headers=headers,
            json={
                "expected_token": current["token"],
                "readiness": "complete",
                "lines": [
                    {"component_revision_id": m.current_revision_id, "quantity": "400", "uom": "mm"}
                ],
            },
        )
        assert changed.status_code == 200
        stale = client.put(
            base + "/material-bom",
            headers=headers,
            json={"expected_token": current["token"], "lines": []},
        )
        assert stale.status_code == 409
        usage = client.get(f"/api/v1/items/{m.id}/material-where-used", headers=headers)
        assert usage.json()[0]["parent_revision_id"] == p.current_revision_id
        snapshot = client.post(
            "/api/v1/requirements/calculate",
            headers=headers,
            json={
                "roots": [{"root_revision_id": p.current_revision_id, "quantity": "6"}],
                "save": True,
            },
        )
        assert snapshot.status_code == 200
        export = client.get(
            f"/api/v1/requirements/snapshots/{snapshot.json()['id']}/csv", headers=headers
        )
        assert export.status_code == 200 and "M000001,2.400,m" in export.text
        assert (
            client.get(f"/api/v1/requirements/snapshots/{snapshot.json()['id']}").status_code == 401
        )


def test_purchased_inputs_cannot_duplicate_ebom(backend):
    b = backend
    svc = service(b)
    user = b.users["editor"]
    s = b.items.create_item(
        kind=ItemKind.PART, number_series="S", name="Bearing", description="", created_by=user.id
    )
    a = create_item(b, kind="assembly")
    b.bom.replace_bom(
        user,
        a.current_revision_id,
        [{"component_revision_id": s.current_revision_id, "quantity": "1", "position": 1}],
    )
    with pytest.raises(Conflict, match="already occurs"):
        svc.replace(
            user,
            a.current_revision_id,
            [{"component_revision_id": s.current_revision_id, "quantity": "1", "uom": "ea"}],
            svc.read(user, a.current_revision_id)["token"],
        )
    with pytest.raises(Conflict, match="raw materials"):
        m = material(b)
        b.bom.replace_bom(
            user,
            a.current_revision_id,
            [{"component_revision_id": m.current_revision_id, "quantity": "1", "position": 1}],
        )


def test_snapshot_rechecks_empty_private_branches(backend):
    from datetime import UTC, datetime
    from uuid import uuid4

    b = backend
    user = b.users["admin"]
    private = str(uuid4())
    with b.database.transaction() as c:
        c.execute(
            "INSERT INTO projects(id,project_number,name,archived,created_at) VALUES (?,'PRIVATE-MATERIAL','Private material test',0,?)",
            (private, datetime.now(UTC).isoformat()),
        )
    child = b.items.create_item(
        kind=ItemKind.PART,
        name="Private child",
        description="",
        project_id=private,
        created_by=user.id,
    )
    root = b.items.create_item(
        kind=ItemKind.ASSEMBLY,
        name="Public root",
        description="",
        project_id=b.project_id,
        created_by=user.id,
    )
    b.bom.replace_bom(
        user,
        root.current_revision_id,
        [{"component_revision_id": child.current_revision_id, "quantity": "1", "position": 1}],
    )
    svc = service(b)
    snapshot = svc.calculate(
        user, [{"root_revision_id": root.current_revision_id, "quantity": "1"}], save=True
    )
    assert not snapshot["lines"]
    with pytest.raises(Forbidden):
        svc.snapshot(b.users["viewer"], snapshot["id"])
