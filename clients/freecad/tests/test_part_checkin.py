"""Durable operation recovery must preserve original bytes and avoid duplicates."""

import io
import json
import os
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

import pytest

from freecad.forgepdm import part_checkin, workspace as ws
from freecad.forgepdm.api import ForgePDMError


def native(note=""):
    content = io.BytesIO()
    with ZipFile(content, "w") as archive:
        archive.writestr("Document.xml", "<Document><Objects/><ObjectData/>" + note + "</Document>")
    return content.getvalue()


class Client:
    base_url = "http://part-checkin.test"

    def __init__(self, actor):
        self.actor = actor
        self.checkout = {"id": str(uuid4()), "version": 1, "user_id": actor}
        self.results = {}
        self.manifests = {}
        self.sent = []
        self.lose_response = False
        self.after_send = lambda: None

    def _checkpoint(self):
        pass

    def get_checkout(self, revision):
        return self.checkout

    def part_checkin_status(self, revision, key):
        return self.results.get(key)

    def get_manifest(self, dataset):
        return self.manifests[dataset]

    def upload_part_checkin(self, path, operation):
        assert ws.digest(path) == (operation["content_hash"], operation["byte_size"])
        self.sent.append(dict(operation))
        dataset, file = str(uuid4()), str(uuid4())
        result = {
            "operation_id": operation["operation_id"],
            "revision_id": operation["revision_id"],
            "status": "completed",
            "dataset": {
                "id": dataset,
                "revision_id": operation["revision_id"],
                "created_by": self.actor,
                "dataset_type": "native_cad",
                "files": [
                    {
                        "id": file,
                        "content_hash": operation["content_hash"],
                        "byte_size": operation["byte_size"],
                    }
                ],
            },
        }
        self.results[operation["operation_id"]] = result
        self.manifests[dataset] = {
            "source_file_id": file,
            "profile": "freecad-app-link-v1",
            "references": operation.get("references", []),
        }
        self.checkout = None
        self.after_send()
        if self.lose_response:
            self.lose_response = False
            raise ForgePDMError("lost response", code="connection_failed")
        return result


def case(tmp_path):
    actor, item, revision = [str(uuid4()) for _ in range(3)]
    client = Client(actor)
    path = Path(ws.prepare_working(client.base_url, tmp_path))
    path.write_bytes(native())
    args = (client, str(path), revision, item, actor)
    return client, path, args


def journal(path):
    return json.loads((path.parent / part_checkin.JOURNAL).read_text())


def test_lost_response_recovers_original_result_without_duplicate_or_checkout(tmp_path):
    client, path, args = case(tmp_path)
    client.lose_response = True
    with pytest.raises(ForgePDMError):
        part_checkin.checkin(*args)
    operation = journal(path)
    assert operation["state"] == "prepared"
    if os.name == "posix":
        assert (path.parent / part_checkin.JOURNAL).stat().st_mode & 0o077 == 0
        assert (tmp_path / operation["snapshot_path"]).stat().st_mode & 0o077 == 0
    assert "token" not in operation
    result = part_checkin.resume(*args)
    assert result["operation_id"] == operation["operation_id"]
    assert len(client.sent) == 1 and client.checkout is None
    assert journal(path)["state"] == "acknowledged"
    assert not Path(tmp_path / operation["snapshot_path"]).exists()
    assert ws.binding(path, client.base_url)["entry"]["working_hash"] == operation["content_hash"]
    # A repeated click without a new checkout remains an idempotent confirmation.
    assert part_checkin.resume(*args)["operation_id"] == operation["operation_id"]
    assert len(client.sent) == 1


def test_changed_local_file_is_not_substituted_for_pending_snapshot(tmp_path):
    client, path, args = case(tmp_path)
    original = path.read_bytes()
    client.lose_response = True
    with pytest.raises(ForgePDMError):
        part_checkin.checkin(*args)
    path.write_bytes(native('<Note value="new edits"/>'))
    edited = path.read_bytes()
    result = part_checkin.resume(*args)
    assert result["local_changes_remain"] and path.read_bytes() == edited
    assert result["dataset"]["files"][0]["byte_size"] == len(original)
    assert len(client.sent) == 1


def test_local_ledger_failure_after_commit_remains_recoverable(tmp_path, monkeypatch):
    client, path, args = case(tmp_path)
    original = ws._atomic_json

    def fail_ledger(destination, value):
        if destination.name == ws.MANIFEST:
            raise OSError("injected ledger failure")
        return original(destination, value)

    monkeypatch.setattr(ws, "_atomic_json", fail_ledger)
    with pytest.raises(OSError):
        part_checkin.checkin(*args)
    assert journal(path)["state"] == "committed"
    monkeypatch.setattr(ws, "_atomic_json", original)
    part_checkin.resume(*args)
    assert journal(path)["state"] == "acknowledged" and len(client.sent) == 1


def test_next_checkout_creates_a_new_operation_only_after_acknowledgment(tmp_path):
    client, path, args = case(tmp_path)
    first = part_checkin.checkin(*args)
    client.checkout = {"id": str(uuid4()), "version": 1, "user_id": client.actor}
    second = part_checkin.checkin(*args)
    assert first["operation_id"] != second["operation_id"] and len(client.sent) == 2


def test_foreign_actor_cannot_resume_another_users_journal(tmp_path):
    client, path, args = case(tmp_path)
    client.lose_response = True
    with pytest.raises(ForgePDMError):
        part_checkin.checkin(*args)
    with pytest.raises(ws.WorkspaceError, match="different user"):
        part_checkin.resume(*args[:-1], str(uuid4()))
    assert journal(path)["state"] == "prepared"


def test_pending_bytes_are_verified_and_original_lease_is_not_silently_replaced(tmp_path):
    client, path, args = case(tmp_path)

    def rejected(path, operation):
        raise ForgePDMError("stale checkout", status=409)

    client.upload_part_checkin = rejected
    with pytest.raises(ForgePDMError):
        part_checkin.checkin(*args)
    operation = journal(path)
    with pytest.raises(ws.WorkspaceError, match="original lease is still valid"):
        part_checkin.abandon(*args)
    client.checkout = {"id": str(uuid4()), "version": 1, "user_id": client.actor}
    part_checkin.abandon(*args)
    assert not (path.parent / part_checkin.JOURNAL).exists()
    assert (path.parent / ("part-checkin-" + operation["operation_id"] + ".json")).exists()
    assert (tmp_path / operation["snapshot_path"]).exists()


def test_interrupted_uncommitted_upload_resends_same_operation_and_snapshot(tmp_path):
    client, path, args = case(tmp_path)
    send = client.upload_part_checkin

    def interrupt(snapshot, operation):
        raise OSError("connection interrupted before commit")

    client.upload_part_checkin = interrupt
    with pytest.raises(OSError):
        part_checkin.checkin(*args)
    operation = journal(path)
    path.write_bytes(native('<Note value="edited"/>'))
    client.upload_part_checkin = send
    result = part_checkin.resume(*args)
    assert result["operation_id"] == operation["operation_id"]
    assert client.sent[0]["expected_checkout_id"] == operation["expected_checkout_id"]
    assert result["local_changes_remain"]


def test_corrupted_pending_snapshot_is_not_replaced_or_sent(tmp_path):
    client, path, args = case(tmp_path)
    client.upload_part_checkin = lambda *args: (_ for _ in ()).throw(OSError("offline"))
    with pytest.raises(OSError):
        part_checkin.checkin(*args)
    snapshot = tmp_path / journal(path)["snapshot_path"]
    snapshot.chmod(0o600)
    snapshot.write_bytes(b"corrupted")
    with pytest.raises(ws.WorkspaceError, match="snapshot changed"):
        part_checkin.resume(*args)
    assert not client.sent


def test_late_recovery_does_not_overwrite_newer_local_operation(tmp_path):
    client, path, args = case(tmp_path)

    def newer_journal():
        value = journal(path)
        value["operation_id"] = str(uuid4())
        ws._atomic_json(path.parent / part_checkin.JOURNAL, value)

    client.after_send = newer_journal
    with pytest.raises(ws.WorkspaceError, match="newer local"):
        part_checkin.checkin(*args)
    assert journal(path)["operation_id"] != client.sent[0]["operation_id"]
    assert len(client.results) == 1


def test_assembly_retry_retains_original_pins_after_component_and_local_edits(tmp_path):
    from test_workspace import Client as GraphClient, native as linked_native

    client, path, args = case(tmp_path)
    graph = GraphClient()
    graph.base_url = client.base_url
    revision, dataset, file = graph.add(native())
    configuration = ws.retrieve(graph, tmp_path, revision, dataset, file)
    ws.finish(graph, configuration)
    child_path = str(
        Path(configuration["directory"]) / configuration["ledger"]["documents"][0]["path"]
    )
    child = graph.get_revision(revision)
    references = [
        {
            "object_name": "Subassembly",
            "property_name": "LinkedObject",
            "target_object_name": "Box",
            "target_revision_id": revision,
            "target_item_id": child["item_id"],
            "target_path": child_path,
        }
    ]
    path.write_bytes(linked_native([("Subassembly", child_path, "Box")]))
    client.lose_response = True
    with pytest.raises(ForgePDMError):
        part_checkin.checkin(*args, references)
    pending = journal(path)
    pins = pending["references"]
    assert pins[0]["target_file_id"] == file and pins[0]["target_dataset_id"] == dataset
    assert "target_path" not in pins[0]
    # The old operation resolves using its original pins even if components are now unavailable.
    Path(child_path).unlink()
    path.write_bytes(native('<Note value="different assembly"/>'))
    result = part_checkin.resume(*args)
    assert result["local_changes_remain"] and len(client.sent) == 1
    assert ws.binding(path, client.base_url)["entry"]["references"] == pins


def test_changed_manifest_after_commit_is_not_acknowledged(tmp_path):
    client, path, args = case(tmp_path)

    def wrong_manifest():
        next(iter(client.manifests.values()))["references"] = [{"object_name": "unexpected"}]

    client.after_send = wrong_manifest
    with pytest.raises(ws.WorkspaceError, match="manifest is inconsistent"):
        part_checkin.checkin(*args)
    assert journal(path)["state"] == "committed"
    assert (tmp_path / journal(path)["snapshot_path"]).exists()


def test_060_pending_journal_without_references_is_still_recoverable(tmp_path):
    client, path, args = case(tmp_path)
    client.lose_response = True
    with pytest.raises(ForgePDMError):
        part_checkin.checkin(*args)
    previous = journal(path)
    del previous["references"]
    ws._atomic_json(path.parent / part_checkin.JOURNAL, previous)
    result = part_checkin.resume(*args)
    assert result["operation_id"] == previous["operation_id"]
    assert journal(path)["state"] == "acknowledged" and len(client.sent) == 1
