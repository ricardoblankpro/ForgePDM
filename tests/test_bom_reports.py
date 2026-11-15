"""Shared presentations preserve quantities, exact pins, mass and snapshot evidence."""

from decimal import Decimal

import pytest
from conftest import create_item
from test_assembly_mass import setup

from forgepdm.application import bom_reports
from forgepdm.application.bom_reports import bom_report
from forgepdm.domain.entities import Conflict, Forbidden, LifecycleState


def read(b, root, user="viewer"):
    return bom_report(b.database, b.authorization, b.users[user], root.current_revision_id)


def test_repeated_subassemblies_and_fractional_quantities_share_leaf_rollup(backend):
    b = backend
    root, child, screw, lines, _ = setup(b)
    lines(root, [(child, "3"), (child, "0.2"), (screw, "2")])
    before = b.bom.get_bom(b.users["editor"], root.current_revision_id, True)
    result = read(b, root)
    direct, indented, flat = (result["views"][key] for key in bom_reports.VIEWS)
    assert [v["quantity"] for v in direct] == ["3", "0.2", "2"]
    assert [Decimal(v["quantity"]) for v in indented] == list(
        map(Decimal, ["3", "7.5", "0.2", "0.50", "2"])
    )
    assert [v["quantity_per_parent"] for v in indented] == ["3", "2.5", "0.2", "2.5", "2"]
    assert [v["position"] for v in indented] == ["1", "1.1", "2", "2.1", "3"]
    assert indented[1]["parent_key"] == indented[0]["row_key"]
    assert indented[1]["row_key"] != indented[3]["row_key"]
    assert len(flat) == 1 and flat[0]["component_revision_id"] == screw.current_revision_id
    assert Decimal(flat[0]["quantity"]) == 10
    assert len(flat[0]["occurrences"]) == 3
    assert Decimal(flat[0]["total_mass"]) == Decimal(result["mass"]["mass_kg"]) == Decimal("0.085")
    assert Decimal(direct[0]["unit_mass"]) == Decimal("0.02125")
    assert Decimal(direct[0]["total_mass"]) == Decimal("0.06375")
    assert result["structure_complete"]
    assert before == b.bom.get_bom(b.users["editor"], root.current_revision_id, True)
    assert read(b, root)["token"] == result["token"]


def test_flattening_keeps_revisions_separate_and_does_not_select_latest(backend):
    b = backend
    root, child, screw, _lines, _ = setup(b)
    user = b.users["editor"]
    b.revisions.check_in(user, screw.current_revision_id)
    b.revisions.transition_lifecycle(user, screw.current_revision_id, LifecycleState.RELEASED)
    newer, _ = b.revisions.create_next_revision(user, screw.id, "Second revision")
    b.bom.replace_bom(
        user,
        root.current_revision_id,
        [
            {"component_revision_id": child.current_revision_id, "quantity": "3", "position": 4},
            {"component_revision_id": newer.id, "quantity": "1.5", "position": 7},
        ],
    )
    result = read(b, root)
    rows = result["views"]["flattened"]
    assert [r["component_revision_id"] for r in rows] == [screw.current_revision_id, newer.id]
    assert [Decimal(r["quantity"]) for r in rows] == [Decimal("7.5"), Decimal("1.5")]
    # Revision creation retains its reference mass; aggregation still keeps pins separate.
    assert Decimal(result["mass"]["mass_kg"]) == Decimal("0.0765")
    assert rows[0]["unit_mass"] == rows[1]["unit_mass"]


def test_empty_assembly_and_unknown_mass_are_explicit(backend):
    b = backend
    root, child, screw, lines, _ = setup(b)
    empty, unknown = create_item(b, kind="assembly"), create_item(b)
    lines(child, [(empty, "2"), (unknown, "1"), (screw, "1")])
    result = read(b, root)
    assert not result["structure_complete"]
    assert result["structure_issues"][0]["revision_id"] == empty.current_revision_id
    assert Decimal(result["structure_issues"][0]["quantity"]) == 6
    assert result["views"]["direct"][0]["unit_mass"] is None
    assert result["mass"]["mass_kg"] is None
    assert Decimal(result["mass"]["known_mass_kg"]) == Decimal("0.0425")
    assert {r["component_revision_id"] for r in result["views"]["flattened"]} == {
        screw.current_revision_id,
        unknown.current_revision_id,
    }


def test_descendant_permission_denies_every_view_and_mass(backend):
    b = backend
    root, child, _screw, lines, _ = setup(b)
    part = create_item(b)
    lines(child, [(part, "1")])
    with b.database.transaction() as c:
        c.execute("DELETE FROM project_items WHERE item_id=?", (part.id,))
    with pytest.raises(Forbidden):
        read(b, root)


@pytest.mark.parametrize("limit", ["MAX_NODES", "MAX_DEPTH"])
def test_report_limits_fail_instead_of_truncating(backend, monkeypatch, limit):
    b = backend
    root, *_ = setup(b)
    monkeypatch.setattr(bom_reports, limit, 1)
    with pytest.raises(Conflict, match="limits"):
        read(b, root)


@pytest.mark.parametrize("quantity", ["NaN", "Infinity", "0", "-1", "1e31", "bad"])
def test_corrupt_or_excessive_quantities_fail(backend, quantity):
    b = backend
    root, child, *_ = setup(b)
    with b.database.transaction() as c:
        c.execute(
            "UPDATE bom_lines SET quantity=? WHERE parent_revision_id=?",
            (quantity, child.current_revision_id),
        )
    with pytest.raises(Conflict, match="quantity"):
        read(b, root)


def test_replaced_line_ids_preserve_annotation_keys_but_update_evidence(backend):
    b = backend
    root, child, screw, lines, _ = setup(b)
    before = read(b, root)
    lines(child, [(screw, "2.5")])
    after = read(b, root)
    assert before["token"] != after["token"]
    for view in bom_reports.VIEWS:
        assert [r["row_key"] for r in before["views"][view]] == [
            r["row_key"] for r in after["views"][view]
        ]


def test_read_snapshot_does_not_mix_concurrent_quantity_updates(backend):
    from threading import Thread
    from types import SimpleNamespace

    b = backend
    root, child, *_ = setup(b)
    changed = []

    def require(user, rid, c):
        b.authorization.require_read_revision(user, rid, c)
        if rid == child.current_revision_id:

            def update():
                with b.database.transaction() as writer:
                    writer.execute(
                        "UPDATE bom_lines SET quantity='8' WHERE parent_revision_id=?",
                        (child.current_revision_id,),
                    )
                changed.append(True)

            worker = Thread(target=update)
            worker.start()
            worker.join(timeout=5)
            assert not worker.is_alive()

    authorization = SimpleNamespace(require_read_revision=require)
    result = bom_report(b.database, authorization, b.users["viewer"], root.current_revision_id)
    assert changed
    assert Decimal(result["views"]["flattened"][0]["quantity"]) == Decimal("9.5")
    assert Decimal(read(b, root)["views"]["flattened"][0]["quantity"]) == 26


def test_report_api_authentication_and_legacy_projection(backend):
    from fastapi.testclient import TestClient

    from forgepdm.api.v1.routes import current_user
    from forgepdm.main import create_app

    b = backend
    root, *_ = setup(b)
    app = create_app(b.database.path)
    path = f"/api/v1/revisions/{root.current_revision_id}"
    with TestClient(app) as client:
        assert client.get(path + "/bom-report").status_code == 401
        app.dependency_overrides[current_user] = lambda: b.users["viewer"]
        response = client.get(path + "/bom-report")
        assert response.status_code == 200
        result = response.json()
        assert set(result["views"]) == set(bom_reports.VIEWS)
        legacy = client.get(path + "/drawing-bom").json()
        assert legacy["lines"] == result["views"]["direct"]
        assert legacy["token"] == result["token"]
        assert client.get(path + "/assembly-mass").json() == result["mass"]


def test_quantity_multiplication_keeps_more_than_default_decimal_precision(backend):
    from decimal import localcontext

    b = backend
    root, child, *_ = setup(b)
    quantity = "0.12345678901234567890123456789012"
    with b.database.transaction() as c:
        c.execute(
            "UPDATE bom_lines SET quantity=? WHERE parent_revision_id IN (?,?)",
            (quantity, root.current_revision_id, child.current_revision_id),
        )
    result = read(b, root)
    with localcontext() as context:
        context.prec = 4096
        expected = Decimal(quantity) ** 2 + Decimal(quantity)
    assert Decimal(result["views"]["flattened"][0]["quantity"]) == expected


def test_estimated_leaf_marks_subassembly_and_all_report_presentations(backend):
    from test_mass_fallbacks import estimate
    from test_reference_mass import service

    b = backend
    root, _, screw, _, _ = setup(b)
    # Start this fixture without the higher-priority manual mass from setup.
    with b.database.transaction() as c:
        c.execute(
            "DELETE FROM revision_reference_mass WHERE revision_id=?", (screw.current_revision_id,)
        )
    svc = service(b)
    svc.save_fallback(b.users["editor"], screw.current_revision_id, estimate(svc, b, screw))
    result = read(b, root)
    assert result["mass"]["contains_cad_estimates"]
    assert all(
        row["mass_source"]["status"] == "cad_estimate"
        for view in result["views"].values()
        for row in view
    )
