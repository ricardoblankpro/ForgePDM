"""Assembly totals preserve pins, quantities, unknowns and authorization."""

from decimal import Decimal

import pytest
from conftest import create_item
from test_mass_fallbacks import estimate, manual
from test_reference_mass import create_standard, service

from forgepdm.application.assembly_mass import AssemblyMassService
from forgepdm.domain.entities import Conflict, Forbidden


def setup(b):
    root = create_item(b, kind="assembly")
    child = create_item(b, kind="assembly")
    screw = create_standard(b)
    svc = service(b)
    svc.save_fallback(b.users["editor"], screw.current_revision_id, manual(svc, b, screw))

    def lines(parent, entries):
        return b.bom.replace_bom(
            b.users["editor"],
            parent.current_revision_id,
            [
                {"component_revision_id": item.current_revision_id, "quantity": q, "position": i}
                for i, (item, q) in enumerate(entries, 1)
            ],
        )

    lines(child, [(screw, "2.5")])
    lines(root, [(child, "3"), (screw, "2")])
    return root, child, screw, lines, AssemblyMassService(b.database, b.authorization)


def test_nested_repeated_fractional_and_live_source_update(backend):
    b = backend
    root, _child, screw, _lines, roll = setup(b)
    result = roll.read(b.users["viewer"], root.current_revision_id)
    assert result["status"] == "complete"
    assert Decimal(result["mass_kg"]) == Decimal("0.08075")
    assert [Decimal(v["quantity"]) for v in result["components"]] == [Decimal("7.5"), Decimal(2)]
    assert all(v["revision_id"] == screw.current_revision_id for v in result["components"])
    svc = service(b)
    svc.save_fallback(
        b.users["editor"], screw.current_revision_id, manual(svc, b, screw, mass_g="10")
    )
    assert Decimal(roll.read(b.users["viewer"], root.current_revision_id)["mass_kg"]) == Decimal(
        "0.095"
    )


def test_unknown_part_and_empty_assembly_never_become_zero_total(backend):
    b = backend
    root, _child, screw, lines, roll = setup(b)
    unknown = create_item(b)
    empty = create_item(b, kind="assembly")
    lines(root, [(screw, "2"), (unknown, "1"), (empty, "1")])
    result = roll.read(b.users["editor"], root.current_revision_id)
    assert result["mass_kg"] is None
    assert Decimal(result["known_mass_kg"]) == Decimal("0.017")
    assert len(result["issues"]) == 2
    assert {v["revision_id"] for v in result["issues"]} == {
        unknown.current_revision_id,
        empty.current_revision_id,
    }


def test_estimate_provenance_and_wrong_root(backend):
    b = backend
    root = create_item(b, kind="assembly")
    screw = create_standard(b)
    svc = service(b)
    svc.save_fallback(b.users["editor"], screw.current_revision_id, estimate(svc, b, screw))
    b.bom.replace_bom(
        b.users["editor"],
        root.current_revision_id,
        [{"component_revision_id": screw.current_revision_id, "quantity": "2", "position": 1}],
    )
    roll = AssemblyMassService(b.database, b.authorization)
    assert roll.read(b.users["viewer"], root.current_revision_id)["contains_cad_estimates"]
    with pytest.raises(Conflict):
        roll.read(b.users["viewer"], screw.current_revision_id)


def test_published_part_source_and_changed_material_invalidate_total(backend):
    import io
    import json

    from forgepdm.domain.entities import DatasetType

    b = backend
    root, _child, screw, lines, roll = setup(b)
    part = create_item(b)
    dataset, file = b.datasets.attach_file(
        user=b.users["editor"],
        revision_id=part.current_revision_id,
        dataset_type=DatasetType.NATIVE_CAD,
        dataset_name="part",
        filename="part.FCStd",
        media_type="application/octet-stream",
        source=io.BytesIO(b"test geometry"),
    )
    with b.database.transaction() as c:
        c.execute(
            "INSERT INTO dataset_part_mass VALUES (?,?)",
            (dataset.id, json.dumps({"mass_kg": "7.8", "physical_material": None})),
        )
    lines(root, [(part, "2"), (screw, "1")])
    result = roll.read(b.users["viewer"], root.current_revision_id)
    assert Decimal(result["mass_kg"]) == Decimal("15.6085")
    assert result["components"][0]["source"]["content_hash"] == file.content_hash
    with b.database.transaction() as c:
        c.execute(
            "INSERT INTO part_physical_assignments VALUES (?,?)",
            (part.current_revision_id, json.dumps({"changed": True})),
        )
    result = roll.read(b.users["viewer"], root.current_revision_id)
    assert result["mass_kg"] is None
    assert "assignment changed" in result["issues"][0]["reason"]


def test_http_contract(backend, monkeypatch):
    from fastapi.testclient import TestClient

    from forgepdm.api.v1.routes import current_user
    from forgepdm.main import create_app

    b = backend
    root, _child, screw, _lines, _roll = setup(b)
    app = create_app(b.database.path)
    app.dependency_overrides[current_user] = lambda: b.users["viewer"]
    with TestClient(app) as client:
        response = client.get(f"/api/v1/revisions/{root.current_revision_id}/assembly-mass")
        assert response.status_code == 200
        assert Decimal(response.json()["mass_kg"]) == Decimal("0.08075")
        assert (
            client.get(f"/api/v1/revisions/{screw.current_revision_id}/assembly-mass").status_code
            == 409
        )
        app.dependency_overrides.clear()
        assert (
            client.get(f"/api/v1/revisions/{root.current_revision_id}/assembly-mass").status_code
            == 401
        )


def test_inaccessible_child_fails_entire_rollup_and_corrupt_cycle_is_bounded(backend):
    b = backend
    root, child, _screw, _lines, roll = setup(b)
    with b.database.transaction() as c:
        c.execute(
            "DELETE FROM project_items WHERE item_id=?",
            (child.id,),
        )
    with pytest.raises(Forbidden):
        roll.read(b.users["viewer"], root.current_revision_id)
    with b.database.transaction() as c:
        c.execute(
            "UPDATE bom_lines SET component_revision_id=? WHERE parent_revision_id=?",
            (root.current_revision_id, child.current_revision_id),
        )
    with pytest.raises(Conflict, match="cycle"):
        roll.read(b.users["admin"], root.current_revision_id)


def test_newer_revision_does_not_change_existing_pins(backend):
    from forgepdm.domain.entities import LifecycleState

    b = backend
    root, _child, screw, _lines, roll = setup(b)
    user = b.users["editor"]
    b.revisions.check_in(user, screw.current_revision_id)
    b.revisions.transition_lifecycle(user, screw.current_revision_id, LifecycleState.RELEASED)
    newer, _ = b.revisions.create_next_revision(user, screw.id, "New mass")
    svc = service(b)
    svc.save_fallback(
        user,
        newer.id,
        {
            "method": "manual",
            "mass_g": "100",
            "note": "",
            "expected_token": svc.read(user, newer.id)["token"],
        },
    )
    result = roll.read(user, root.current_revision_id)
    assert Decimal(result["mass_kg"]) == Decimal("0.08075")
    assert all(v["revision_id"] == screw.current_revision_id for v in result["components"])
