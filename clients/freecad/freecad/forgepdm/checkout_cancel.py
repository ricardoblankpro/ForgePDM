"""Durable cancellation intent, separate from GUI restoration and credentials."""

import json
from uuid import UUID, uuid4

from . import part_checkin, workspace as ws

JOURNAL = "checkout-cancel.json"


def prepare(client, path, revision_id, actor_id):
    value = ws.binding(path, client.base_url, require_uploaded=False)
    journal = value["directory"] / JOURNAL
    with ws.locked(value["root"], client.base_url):
        if journal.is_symlink():
            raise ws.WorkspaceError("Cancellation journal must not be linked")
        if journal.exists():
            intent = json.loads(journal.read_text())
            if (intent["server_url"], intent["actor_id"], intent["revision_id"]) != (
                client.base_url,
                actor_id,
                revision_id,
            ):
                raise ws.WorkspaceError("Cancellation belongs to another user or revision")
            operation = str(UUID(intent["payload"]["operation_id"]))
            expected_recovery = ws._safe_path(value["root"], ".forgepdm/recovery/" + operation)
            if (
                intent.get("format") != 1
                or intent.get("source_path") != path
                or intent.get("recovery") != str(expected_recovery)
            ):
                raise ws.WorkspaceError(
                    "Cancellation recovery identity is corrupt; preserve its journal"
                )
            if intent["state"] not in ("prepared", "restored", "released", "complete"):
                raise ws.WorkspaceError("Unknown cancellation state; preserve its journal")
            if intent["state"] != "complete":
                return intent
        pending = value["directory"] / part_checkin.JOURNAL
        if pending.exists() and json.loads(pending.read_text()).get("state") != "acknowledged":
            raise ws.WorkspaceError("Recover the pending Check In before cancelling checkout")
        for filename, done in (
            ("graph-publication.json", "complete"),
            ("drawing-publication.json", "acknowledged"),
        ):
            pending = value["directory"] / filename
            if pending.exists() and (
                pending.is_symlink() or json.loads(pending.read_text()).get("state") != done
            ):
                raise ws.WorkspaceError("Recover pending publication before cancelling checkout")
        checkout = client.get_checkout(revision_id)
        if not checkout or checkout["user_id"] != actor_id:
            raise ws.WorkspaceError("Cancel Check Out requires your active checkout")
        snapshots = [
            (d, f)
            for d in client.list_datasets(revision_id)
            if d["dataset_type"] == "native_cad"
            for f in d["files"]
        ]
        latest = (
            max(snapshots, key=lambda pair: (pair[0]["created_at"], pair[0]["id"], pair[1]["id"]))
            if snapshots
            else None
        )
        operation = str(uuid4())
        recovery = value["root"] / ".forgepdm" / "recovery" / operation
        recovery.mkdir(parents=True)
        intent = dict(
            format=1,
            server_url=client.base_url,
            actor_id=actor_id,
            revision_id=revision_id,
            state="prepared",
            recovery=str(recovery),
            source_path=path,
            payload=dict(
                operation_id=operation,
                expected_checkout_id=checkout["id"],
                expected_checkout_version=checkout["version"],
                dataset_id=latest[0]["id"] if latest else None,
                file_id=latest[1]["id"] if latest else None,
            ),
        )
        ws._atomic_json(journal, intent)
        return intent


def record(client, path, intent, state):
    value = ws.binding(path, client.base_url, require_uploaded=False)
    with ws.locked(value["root"], client.base_url):
        intent = dict(intent, state=state)
        ws._atomic_json(value["directory"] / JOURNAL, intent)
    return intent


def release(client, intent):
    previous = client.cancellation_status(intent["revision_id"], intent["payload"]["operation_id"])
    return (
        previous
        if previous is not None
        else client.cancel_checkout(intent["revision_id"], intent["payload"])
    )
