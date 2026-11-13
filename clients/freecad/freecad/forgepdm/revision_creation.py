"""Credential-free durable intent for revision creation and lost-response recovery."""

import hashlib
import json
import os
from pathlib import Path
from uuid import UUID, uuid4

from . import workspace as ws


def _location(client, item_id, source_revision_id):
    actor = client._json_request("GET", "/api/v1/auth/me")["id"]
    identity = {
        "server_url": client.base_url,
        "actor_id": actor,
        "item_id": str(UUID(item_id)),
        "source_revision_id": str(UUID(source_revision_id)),
    }
    root = (
        Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
        / "forgepdm/revision-operations"
    )
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink():
        raise ws.WorkspaceError("Revision journal directory must not be a symlink")
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    directory = root / key
    if directory.is_symlink():
        raise ws.WorkspaceError("Revision operation directory must not be a symlink")
    directory.mkdir(exist_ok=True, mode=0o700)
    return directory / "operation.json", identity


def _read(path, identity):
    if path.is_symlink():
        raise ws.WorkspaceError("Revision journal must not be a symlink")
    if not path.exists():
        return None
    value = json.loads(path.read_text())
    if any(value.get(key) != expected for key, expected in identity.items()):
        raise ws.WorkspaceError("Revision journal identity mismatch; preserved for review")
    UUID(value["operation_id"])
    return value


def _finish(client, path, value):
    endpoint = "/api/v1/items/{}/revision-operations/{}".format(
        value["item_id"], value["operation_id"]
    )
    from .api import ForgePDMError

    try:
        result = client._json_request("GET", endpoint)
    except ForgePDMError as error:
        if error.status != 404 or str(error) == "Not Found":
            raise
        result = client._json_request(
            "POST",
            "/api/v1/items/{}/revisions/recoverable".format(value["item_id"]),
            {
                "operation_id": value["operation_id"],
                "expected_source_revision_id": value["source_revision_id"],
                "change_note": value["change_note"],
            },
        )
    if result.get("item_id") != value["item_id"] or result.get("created_by") != value["actor_id"]:
        raise ws.WorkspaceError("Revision result identity mismatch")
    value["result"] = result
    ws._atomic_json(path, value)
    return dict(result, working_copy_path=value.get("working_copy_path"))


def resume(client, item_id, source_revision_id):
    path, identity = _location(client, item_id, source_revision_id)
    with ws.locked(path.parent, client.base_url):
        value = _read(path, identity)
        return _finish(client, path, value) if value else None


def create(client, item_id, change_note, source_revision_id, working_copy_path=None):
    path, identity = _location(client, item_id, source_revision_id)
    with ws.locked(path.parent, client.base_url):
        value = _read(path, identity)
        if value is None:
            value = dict(
                identity,
                operation_id=str(uuid4()),
                change_note=change_note.strip(),
                working_copy_path=working_copy_path,
            )
            ws._atomic_json(path, value)
        if value["change_note"] != change_note.strip():
            raise ws.WorkspaceError(
                "A revision operation is already pending with another note; recover it first"
            )
        return _finish(client, path, value)
