"""Transactional stale-review and checkout fencing for CAD BOM synchronization."""

import pytest
from conftest import create_item

from forgepdm.domain.entities import Conflict, Forbidden


def synchronize(backend, revision, lines, snapshot):
    return backend.bom.replace_bom(
        backend.users["editor"],
        revision,
        lines,
        expected_token=snapshot["token"],
        expected_checkout_id=snapshot["checkout_id"],
    )


def test_stale_proposal_cannot_overwrite_manual_lines_or_replay(backend):
    user = backend.users["editor"]
    parent = create_item(backend, kind="assembly").current_revision_id
    child = create_item(backend).current_revision_id
    snapshot = backend.bom.synchronization_snapshot(user, parent)
    lines = [{"component_revision_id": child, "quantity": 2, "position": 1}]
    result = synchronize(backend, parent, lines, snapshot)
    assert result[0]["quantity"] == "2"
    with pytest.raises(Conflict, match="BOM changed"):
        synchronize(backend, parent, [], snapshot)
    assert backend.bom.get_bom(user, parent) == result
    snapshot = backend.bom.synchronization_snapshot(user, parent)
    assert synchronize(backend, parent, [], snapshot) == []


def test_checkout_reacquisition_invalidates_even_an_unchanged_proposal(backend):
    user = backend.users["editor"]
    parent = create_item(backend, kind="assembly").current_revision_id
    snapshot = backend.bom.synchronization_snapshot(user, parent)
    backend.revisions.release_checkout(user, parent)
    backend.revisions.acquire_checkout(user, parent)
    with pytest.raises(Conflict, match="checkout changed"):
        synchronize(backend, parent, [], snapshot)


def test_snapshot_requires_edit_permission_and_owned_checkout(backend):
    parent = create_item(backend, kind="assembly").current_revision_id
    with pytest.raises(Forbidden):
        backend.bom.synchronization_snapshot(backend.users["viewer"], parent)
    with pytest.raises(Conflict):
        backend.bom.synchronization_snapshot(backend.users["editor2"], parent)
    backend.revisions.check_in(backend.users["editor"], parent, "Done")
    with pytest.raises(Conflict):
        backend.bom.synchronization_snapshot(backend.users["editor"], parent)


def test_competing_synchronizations_have_exactly_one_winner(backend):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    parent = create_item(backend, kind="assembly").current_revision_id
    children = [create_item(backend).current_revision_id for _ in range(2)]
    snapshot = backend.bom.synchronization_snapshot(backend.users["editor"], parent)
    barrier = Barrier(2)

    def attempt(child):
        barrier.wait(timeout=5)
        try:
            synchronize(
                backend,
                parent,
                [{"component_revision_id": child, "quantity": 1, "position": 1}],
                snapshot,
            )
            return "committed"
        except Conflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(attempt, children)) == ["committed", "conflict"]


def test_http_synchronization_validates_snapshot_permissions_and_lifecycle(
    backend, monkeypatch, tmp_path
):
    from conftest import TEST_PASSWORD
    from fastapi.testclient import TestClient

    monkeypatch.setenv("FORGEPDM_DATABASE", str(tmp_path / "default.sqlite3"))
    monkeypatch.setenv("FORGEPDM_FILE_ROOT", str(tmp_path / "files"))
    from forgepdm.main import create_app

    parent = create_item(backend, kind="assembly").current_revision_id
    child = create_item(backend).current_revision_id
    path = f"/api/v1/revisions/{parent}/bom"
    with TestClient(create_app(backend.database.path)) as client:

        def login(username):
            response = client.post(
                "/api/v1/auth/login", json={"username": username, "password": TEST_PASSWORD}
            )
            return {"Authorization": "Bearer " + response.json()["access_token"]}

        assert client.get(path + "/snapshot").status_code == 401
        viewer = login("viewer")
        assert client.get(path + "/snapshot", headers=viewer).status_code == 403
        editor = login("editor")
        snapshot = client.get(path + "/snapshot", headers=editor).json()
        payload = {
            "lines": [{"component_revision_id": child, "quantity": 2, "position": 1}],
            "expected_token": snapshot["token"],
            "expected_checkout_id": snapshot["checkout_id"],
        }
        assert (
            client.put(path + "/synchronize", headers=editor, json={"lines": []}).status_code == 422
        )
        assert client.put(path + "/synchronize", headers=viewer, json=payload).status_code == 403
        response = client.put(path + "/synchronize", headers=editor, json=payload)
        assert response.status_code == 200
        assert response.json()[0]["quantity"] == "2"
        assert client.put(path + "/synchronize", headers=editor, json=payload).status_code == 409
        backend.revisions.check_in(backend.users["editor"], parent, "Finished")
        assert client.put(path + "/synchronize", headers=editor, json=payload).status_code == 409
