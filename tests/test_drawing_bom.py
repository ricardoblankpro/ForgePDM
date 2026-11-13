"""Consistent direct drawing data and authorization, without changing the EBOM."""

import pytest
from conftest import create_item

from forgepdm.application.drawing_bom import drawing_bom
from forgepdm.domain.entities import Conflict, Forbidden


def test_report_pins_direct_lines_descriptions_and_unknown_mass(backend):
    b = backend
    parent = create_item(b, kind="assembly")
    child = create_item(b)
    sub = create_item(b, kind="assembly")
    b.bom.replace_bom(
        b.users["editor"],
        parent.current_revision_id,
        [
            {"component_revision_id": child.current_revision_id, "quantity": "2.5", "position": 7},
            {"component_revision_id": sub.current_revision_id, "quantity": "3", "position": 9},
        ],
    )
    with b.database.transaction() as c:
        c.execute(
            "INSERT INTO revision_descriptions VALUES (?,?,NULL)",
            (child.current_revision_id, "STEEL <3 mm>"),
        )
    report = drawing_bom(b.database, b.authorization, b.users["editor"], parent.current_revision_id)
    assert [line["position"] for line in report["lines"]] == [7, 9]
    assert report["lines"][0]["description"] == "STEEL <3 mm>"
    assert report["lines"][0]["material"] == "STEEL <3 mm>"
    assert report["lines"][0]["unit_mass"] is None
    assert report["lines"][1]["total_mass"] is None
    assert (
        report["token"]
        == drawing_bom(b.database, b.authorization, b.users["editor"], parent.current_revision_id)[
            "token"
        ]
    )
    original = b.bom.get_bom(b.users["editor"], parent.current_revision_id)
    assert len(original) == 2 and original[0]["quantity"] == "2.5"
    with b.database.transaction() as c:
        c.execute(
            "UPDATE revision_descriptions SET description='Changed' WHERE revision_id=?",
            (child.current_revision_id,),
        )
    assert (
        report["token"]
        != drawing_bom(b.database, b.authorization, b.users["editor"], parent.current_revision_id)[
            "token"
        ]
    )


def test_report_rejects_nonassembly_and_inaccessible_components(backend):
    b = backend
    part = create_item(b)
    with pytest.raises(Conflict):
        drawing_bom(b.database, b.authorization, b.users["editor"], part.current_revision_id)
    parent = create_item(b, kind="assembly")
    b.bom.replace_bom(
        b.users["editor"],
        parent.current_revision_id,
        [{"component_revision_id": part.current_revision_id, "quantity": "1", "position": 1}],
    )
    with b.database.transaction() as c:
        c.execute("DELETE FROM project_memberships WHERE user_id=?", (b.users["viewer"].id,))
    with pytest.raises(Forbidden):
        drawing_bom(b.database, b.authorization, b.users["viewer"], parent.current_revision_id)


def test_drawing_report_api_requires_auth_and_retains_exact_source(backend, monkeypatch):
    from fastapi.testclient import TestClient
    from conftest import TEST_PASSWORD
    from forgepdm.main import create_app

    b = backend
    monkeypatch.setenv("FORGEPDM_FILE_ROOT", str(b.storage.root))
    parent = create_item(b, kind="assembly")
    path = f"/api/v1/revisions/{parent.current_revision_id}/drawing-bom"
    with TestClient(create_app(b.database.path)) as client:
        assert client.get(path).status_code == 401
        access, _, _ = b.auth.login("editor", TEST_PASSWORD)
        result = client.get(path, headers={"Authorization": "Bearer " + access})
        assert result.status_code == 200
        assert result.json()["revision_id"] == parent.current_revision_id
        assert result.json()["lines"] == []
