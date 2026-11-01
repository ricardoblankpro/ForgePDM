"""Check-in notes are optional; ownership, audit and stored revision notes remain intact."""

import json

import pytest
from conftest import TEST_PASSWORD, create_item
from fastapi.testclient import TestClient

from forgepdm.domain.entities import Conflict


@pytest.mark.parametrize("note", [None, "", "   "])
def test_checkin_without_note_preserves_revision_note_and_releases_checkout(backend, note):
    item = create_item(backend)
    user = backend.users["editor"]
    original = backend.items.get_item(item.id)[1].change_note
    if note is None:
        backend.revisions.check_in(user, item.current_revision_id)
    else:
        backend.revisions.check_in(user, item.current_revision_id, note)
    assert backend.items.get_item(item.id)[1].change_note == original
    assert backend.revisions.current_checkout(user, item.current_revision_id) is None
    with backend.database.connection() as connection:
        event = connection.execute(
            "SELECT details_json FROM audit_events WHERE event_type='revision.checked_in' "
            "AND entity_id=?",
            (item.current_revision_id,),
        ).fetchone()
    assert json.loads(event["details_json"])["change_note"] == ""


def test_checkin_without_note_still_requires_owned_checkout(backend):
    item = create_item(backend)
    with pytest.raises(Conflict):
        backend.revisions.check_in(backend.users["editor2"], item.current_revision_id)
    assert (
        backend.revisions.current_checkout(
            backend.users["editor"], item.current_revision_id
        ).user_id
        == backend.users["editor"].id
    )


@pytest.mark.parametrize(
    "payload",
    [None, {}, {"change_note": ""}, {"change_note": "   "}, {"change_note": "Optional note"}],
)
def test_api_accepts_missing_or_optional_checkin_note(backend, monkeypatch, tmp_path, payload):
    monkeypatch.setenv("FORGEPDM_DATABASE", str(tmp_path / "default.sqlite3"))
    monkeypatch.setenv("FORGEPDM_FILE_ROOT", str(tmp_path / "files"))
    from forgepdm.main import create_app

    item = create_item(backend)
    original = backend.items.get_item(item.id)[1].change_note
    token, _, _ = backend.auth.login("editor", TEST_PASSWORD)
    with TestClient(create_app(backend.database.path)) as client:
        response = client.post(
            f"/api/v1/revisions/{item.current_revision_id}/checkin",
            headers={"Authorization": "Bearer " + token},
            **({"json": payload} if payload is not None else {}),
        )
    assert response.status_code == 204
    assert (
        backend.revisions.current_checkout(backend.users["editor"], item.current_revision_id)
        is None
    )
    assert backend.items.get_item(item.id)[1].change_note == (
        "Optional note" if payload and payload.get("change_note") == "Optional note" else original
    )


def test_oversized_note_is_rejected_without_releasing_checkout(backend):
    item = create_item(backend)
    with pytest.raises(ValueError, match="at most 2000"):
        backend.revisions.check_in(backend.users["editor"], item.current_revision_id, "x" * 2001)
    assert (
        backend.revisions.current_checkout(backend.users["editor"], item.current_revision_id)
        is not None
    )
