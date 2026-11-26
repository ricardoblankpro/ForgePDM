"""Durable, credential-free recovery for one atomic native check-in operation."""

import json
from pathlib import Path
from uuid import UUID, uuid4

from . import fcstd, thumbnail_transfer, workspace as ws

JOURNAL = "part-checkin.json"


def _load(value, client, revision_id, item_id, actor_id):
    path = value["directory"] / JOURNAL
    if not path.exists():
        return None
    if path.is_symlink():
        raise ws.WorkspaceError("Check-in journal must not be a symlink")
    operation = json.loads(path.read_text())
    if any(
        operation.get(key) != expected
        for key, expected in {
            "server_url": client.base_url,
            "revision_id": revision_id,
            "item_id": item_id,
            "actor_id": actor_id,
            "source_path": value["entry"]["path"],
            "format": 1,
        }.items()
    ):
        raise ws.WorkspaceError(
            "Pending check-in belongs to a different user, server or revision; it was preserved"
        )
    if operation.get("state") not in ("prepared", "committed", "acknowledged"):
        raise ws.WorkspaceError("Unknown check-in journal state; it was preserved")
    operation.setdefault("references", [])
    UUID(operation["operation_id"])
    relative = Path(operation["snapshot_path"])
    if (
        len(relative.parts) != 4
        or relative.parts[:2] != (".forgepdm", "uploads")
        or relative.name != "model.FCStd"
    ):
        raise ws.WorkspaceError("Invalid check-in snapshot path")
    UUID(relative.parts[2])
    ws._safe_path(value["root"], operation["snapshot_path"])
    return operation


def _guard_current(value, operation):
    journal = value["directory"] / JOURNAL
    if journal.is_symlink():
        raise ws.WorkspaceError("Check-in journal must not be a symlink")
    current = json.loads(journal.read_text())
    if current.get("references", []) != operation.get("references", []):
        raise ws.WorkspaceError("Pending CAD references changed; journal was preserved")
    if current.get("thumbnail") != operation.get("thumbnail"):
        raise ws.WorkspaceError("Pending preview intent changed; journal was preserved")
    for field in (
        "operation_id",
        "keep_checkout",
        "content_hash",
        "expected_checkout_id",
        "expected_checkout_version",
    ):
        if current.get(field) != operation.get(field):
            raise ws.WorkspaceError(
                "A newer local check-in operation exists; the previous result remains on the server"
            )


def _resolve(client, value, operation):
    result = client.part_checkin_status(operation["revision_id"], operation["operation_id"])
    if result is None:
        if operation["state"] in ("committed", "acknowledged"):
            raise ws.WorkspaceError(
                "Previously committed check-in is no longer on this server; journal was preserved"
            )
        snapshot = ws._safe_path(value["root"], operation["snapshot_path"])
        if ws.digest(snapshot, client._checkpoint) != (
            operation["content_hash"],
            operation["byte_size"],
        ):
            raise ws.WorkspaceError(
                "The pending check-in snapshot changed; no replacement bytes were uploaded"
            )
        fcstd.validate(snapshot, operation.get("references", []))
        result = client.upload_part_checkin(str(snapshot), operation)
    dataset = result.get("dataset", {})
    files = dataset.get("files", [])
    if (
        result.get("operation_id") != operation["operation_id"]
        or result.get("revision_id") != operation["revision_id"]
        or result.get("status") != "completed"
        or len(files) != 1
        or dataset.get("revision_id") != operation["revision_id"]
        or dataset.get("created_by") != operation["actor_id"]
        or (files[0].get("content_hash"), files[0].get("byte_size"))
        != (operation["content_hash"], operation["byte_size"])
    ):
        raise ws.WorkspaceError(
            "Check-in result differs from the recorded operation; journal was preserved"
        )
    record = files[0]
    with ws.locked(value["root"], client.base_url):
        _guard_current(value, operation)
        operation.update(state="committed", result=result)
        ws._atomic_json(value["directory"] / JOURNAL, operation)
    manifest = client.get_manifest(dataset["id"])
    if (
        manifest is None
        or manifest["source_file_id"] != record["id"]
        or manifest["profile"] not in ("freecad-app-link-v1", "freecad-fasteners-v1")
        or manifest["references"] != operation.get("references", [])
    ):
        raise ws.WorkspaceError("The committed CAD manifest is inconsistent; journal was preserved")
    try:
        changed = (
            ws.digest(value["directory"] / operation["source_path"], client._checkpoint)[0]
            != operation["content_hash"]
        )
    except (OSError, ws.WorkspaceError):
        changed = True
    with ws.locked(value["root"], client.base_url):
        _guard_current(value, operation)
        ledger = json.loads((value["directory"] / ws.MANIFEST).read_text())
        entry = next(row for row in ledger["documents"] if row["path"] == operation["source_path"])
        entry.update(
            item_id=operation["item_id"],
            revision_id=operation["revision_id"],
            dataset_id=dataset["id"],
            file_id=record["id"],
            content_hash=record["content_hash"],
            byte_size=record["byte_size"],
            working_hash=record["content_hash"],
            references=operation.get("references", []),
        )
        ws._atomic_json(value["directory"] / ws.MANIFEST, ledger)
        operation["state"] = "acknowledged"
        ws._atomic_json(value["directory"] / JOURNAL, operation)
    snapshot = ws._safe_path(value["root"], operation["snapshot_path"])
    preview_warning = (
        "CAD saved successfully; its preview could not be associated with this snapshot."
        if operation.get("thumbnail_requested") and not operation.get("thumbnail")
        else None
    )
    if operation.get("thumbnail") and operation.get("thumbnail_state") != "completed":
        preview_warning = thumbnail_transfer.send(client, record, snapshot, operation["thumbnail"])
        if not preview_warning:
            with ws.locked(value["root"], client.base_url):
                _guard_current(value, operation)
                operation["thumbnail_state"] = "completed"
                ws._atomic_json(value["directory"] / JOURNAL, operation)
            try:
                thumbnail_transfer.remove(snapshot)
            except OSError:
                pass
    # Only proven internal sidecars/snapshots may be removed after durable records.
    try:
        snapshot.chmod(0o600)
        snapshot.unlink()
        snapshot.parent.rmdir()
    except OSError:
        pass  # A retained local orphan is safer than losing recovery metadata.
    return dict(result, local_changes_remain=changed, thumbnail_warning=preview_warning)


def resume(client, path, revision_id, item_id, actor_id):
    if not path or ws.working_path(path, client.base_url) is None:
        return None
    value = ws.binding(path, client.base_url, require_uploaded=False)
    with ws.locked(value["root"], client.base_url):
        operation = _load(value, client, revision_id, item_id, actor_id)
    if operation and operation["state"] == "acknowledged":
        checkout = client.get_checkout(revision_id)
        if checkout is not None:
            return None
    return _resolve(client, value, operation) if operation else None


def checkin(
    client, path, revision_id, item_id, actor_id, references=(), preview=None, keep_checkout=False
):
    result = resume(client, path, revision_id, item_id, actor_id)
    if result is not None:
        return result
    checkout = client.get_checkout(revision_id)
    if not checkout or checkout["user_id"] != actor_id:
        raise ws.WorkspaceError("Acquire your own checkout before checking in this revision")
    value = ws.binding(path, client.base_url, require_uploaded=False)
    with ws.locked(value["root"], client.base_url):
        operation = _load(value, client, revision_id, item_id, actor_id)
        if (
            operation is not None
            and operation["state"] == "acknowledged"
            and (operation["expected_checkout_id"], operation["expected_checkout_version"])
            != (checkout["id"], checkout["version"])
        ):
            operation = None
        if (
            operation is not None
            and operation["state"] == "acknowledged"
            and (
                bool(operation.get("keep_checkout")) != keep_checkout
                or ws.digest(path)[0] != operation["content_hash"]
            )
        ):
            operation = None
        if operation is None:
            bound = ws.bind_references(client, references)
            saved = ws.snapshot(client, path, bound)
            thumbnail = thumbnail_transfer.prepare(saved, preview)
            serialized = sorted(
                [
                    {key: value for key, value in ref.items() if key != "target_path"}
                    for ref in bound
                ],
                key=lambda ref: (ref["object_name"], ref["property_name"]),
            )
            Path(saved["directory"]).chmod(0o700)
            Path(saved["path"]).chmod(0o400)
            operation = dict(
                references=serialized,
                format=1,
                state="prepared",
                server_url=client.base_url,
                actor_id=actor_id,
                item_id=item_id,
                revision_id=revision_id,
                operation_id=str(uuid4()),
                source_path=value["entry"]["path"],
                expected_checkout_id=checkout["id"],
                expected_checkout_version=checkout["version"],
                content_hash=saved["content_hash"],
                byte_size=saved["byte_size"],
                snapshot_path=Path(saved["path"]).relative_to(value["root"]).as_posix(),
            )
            if keep_checkout:
                operation["keep_checkout"] = True
            if thumbnail:
                operation["thumbnail"] = thumbnail
            if preview is not None:
                operation["thumbnail_requested"] = True
            ws._atomic_json(value["directory"] / JOURNAL, operation)
    return _resolve(client, value, operation)


def abandon(client, path, revision_id, item_id, actor_id):
    value = ws.binding(path, client.base_url, require_uploaded=False)
    with ws.locked(value["root"], client.base_url):
        operation = _load(value, client, revision_id, item_id, actor_id)
    if operation is None:
        return
    if (
        operation["state"] != "prepared"
        or client.part_checkin_status(revision_id, operation["operation_id"]) is not None
    ):
        raise ws.WorkspaceError(
            "This operation committed; recover its result before starting another"
        )
    checkout = client.get_checkout(revision_id)
    if checkout is not None and (checkout["id"], checkout["version"]) == (
        operation["expected_checkout_id"],
        operation["expected_checkout_version"],
    ):
        raise ws.WorkspaceError(
            "The original lease is still valid; resolve its operation before starting another"
        )
    if client.part_checkin_status(revision_id, operation["operation_id"]) is not None:
        raise ws.WorkspaceError("The original operation committed; recover it first")
    with ws.locked(value["root"], client.base_url):
        current = _load(value, client, revision_id, item_id, actor_id)
        if current != operation:
            raise ws.WorkspaceError("Pending operation changed; review it again")
        archive = value["directory"] / ("part-checkin-" + operation["operation_id"] + ".json")
        if archive.exists():
            raise ws.WorkspaceError(
                "A recovery archive already exists; pending operation was preserved"
            )
        ws._atomic_json(archive, dict(operation, state="abandoned"))
        (value["directory"] / JOURNAL).unlink()
