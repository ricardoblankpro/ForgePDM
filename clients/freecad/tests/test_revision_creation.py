"""A new client process recovers the original revision intent after response loss."""

import json
from pathlib import Path
from uuid import uuid4

import pytest

from freecad.forgepdm import revision_creation as rc
from freecad.forgepdm import workspace as ws
from freecad.forgepdm.api import ForgePDMError


class Client:
    base_url = "http://revision-recovery.test"

    def __init__(self):
        self.actor, self.item, self.source = [str(uuid4()) for _ in range(3)]
        self.results, self.sent = {}, []
        self.lose = False
        self.interrupt = False

    def _json_request(self, method, path, payload=None):
        if path.endswith("/auth/me"):
            return {"id": self.actor}
        if method == "GET":
            key = path.rsplit("/", 1)[-1]
            if key not in self.results:
                raise ForgePDMError("revision operation not found", 404)
            return self.results[key]
        assert path.endswith("/revisions/recoverable")
        self.sent.append(dict(payload))
        if self.interrupt:
            raise ForgePDMError("interrupted before commit", code="connection_failed")
        result = {"id": str(uuid4()), "item_id": self.item, "created_by": self.actor, "label": "B"}
        self.results[payload["operation_id"]] = result
        if self.lose:
            self.lose = False
            raise ForgePDMError("lost response", code="connection_failed")
        return result


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    return Client()


def test_response_loss_recovers_same_result_and_copy_without_duplicate_creation(client, tmp_path):
    copy = str(tmp_path / "new.FCStd")
    Path(copy).write_bytes(b"saved original copy")
    client.lose = True
    with pytest.raises(ForgePDMError):
        rc.create(client, client.item, "Next", client.source, copy)
    # Simulate a new process/client with the same authenticated identity.
    fresh = Client()
    fresh.actor, fresh.item, fresh.source = client.actor, client.item, client.source
    fresh.results = client.results
    recovered = rc.resume(fresh, fresh.item, fresh.source)
    assert recovered["id"] == next(iter(client.results.values()))["id"]
    assert recovered["working_copy_path"] == copy
    assert fresh.sent == []
    assert len(client.sent) == 1
    assert Path(copy).read_bytes() == b"saved original copy"
    journal = next(tmp_path.rglob("operation.json"))
    assert "password" not in journal.read_text() and "access_token" not in journal.read_text()
    assert journal.stat().st_mode & 0o077 == 0


def test_interruption_before_commit_retries_original_intent(client):
    client.interrupt = True
    with pytest.raises(ForgePDMError):
        rc.create(client, client.item, "Next", client.source)
    original = client.sent[0]
    client.interrupt = False
    assert rc.resume(client, client.item, client.source)["label"] == "B"
    assert client.sent == [original, original]
    with pytest.raises(ws.WorkspaceError, match="another note"):
        rc.create(client, client.item, "Changed", client.source)


def test_corrupted_or_foreign_journal_fails_closed(client, tmp_path):
    client.interrupt = True
    with pytest.raises(ForgePDMError):
        rc.create(client, client.item, "Next", client.source)
    journal = next(tmp_path.rglob("operation.json"))
    value = json.loads(journal.read_text())
    value["actor_id"] = str(uuid4())
    journal.write_text(json.dumps(value))
    with pytest.raises(ws.WorkspaceError, match="identity mismatch"):
        rc.resume(client, client.item, client.source)
    assert len(client.sent) == 1


def test_journal_symlink_is_rejected(client, tmp_path):
    path, identity = rc._location(client, client.item, client.source)
    target = tmp_path / "untouched.json"
    target.write_text("{}")
    path.symlink_to(target)
    with pytest.raises(ws.WorkspaceError, match="symlink"):
        rc.resume(client, client.item, client.source)
    assert target.read_text() == "{}"
