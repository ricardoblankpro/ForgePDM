"""Credential-free, source-pinned drawing publication journal and frozen PDFs."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4
from zipfile import ZIP_STORED, ZipFile

from . import server_updates, workspace as ws

JOURNAL = "drawing-publication.json"


def _load(client, path, revision_id, item_id, actor_id):
    value = ws.working_path(path, client.base_url) if path else None
    if value is None:
        return None, None
    journal = value["directory"] / JOURNAL
    if journal.is_symlink():
        raise ws.WorkspaceError("Drawing publication journal must not be a symlink")
    if not journal.exists():
        return value, None
    operation = json.loads(journal.read_text())
    for key, expected in dict(
        format=1,
        server_url=client.base_url,
        revision_id=revision_id,
        item_id=item_id,
        actor_id=actor_id,
        source_path=value["entry"]["path"],
    ).items():
        if operation.get(key) != expected:
            raise ws.WorkspaceError(
                "Pending drawing publication belongs to another user, server or document"
            )
    if operation.get("state") not in ("prepared", "acknowledged"):
        raise ws.WorkspaceError("Unknown drawing publication journal state")
    identifier = str(UUID(operation["intent"]["operation_id"]))
    if operation["bundle_path"] != ".forgepdm/drawings/{}/publication.zip".format(identifier):
        raise ws.WorkspaceError("Invalid drawing publication bundle path")
    return value, operation


def prepare(client, path, revision_id, item_id, actor_id):
    value, pending = _load(client, path, revision_id, item_id, actor_id)
    if value is None:
        raise ws.WorkspaceError(
            "Acquire a checkout to create a managed working copy before publishing drawings"
        )
    if pending and pending["state"] == "prepared":
        raise ws.WorkspaceError("Resolve the pending drawing publication first")
    baseline = server_updates.baseline(client, path, item_id, revision_id)
    revision = client.get_revision(revision_id)
    if revision["item_id"] != item_id or revision["lifecycle_state"] != "working":
        raise ws.WorkspaceError("Publish drawings from this item's Working revision")
    checkout = client.get_checkout(revision_id)
    if (
        not checkout
        or checkout["user_id"] != actor_id
        or datetime.fromisoformat(checkout["expires_at"]) <= datetime.now(timezone.utc)
    ):
        raise ws.WorkspaceError("Acquire your own checkout before publishing drawings")
    datasets = client.list_datasets(revision_id)
    source = next(
        (
            ds
            for ds in datasets
            if ds["id"] == baseline["dataset_id"] and ds["dataset_type"] == "native_cad"
        ),
        None,
    )
    record = (
        next((f for f in source["files"] if f["id"] == baseline["file_id"]), None)
        if source
        else None
    )
    if record is None or record["content_hash"] != value["entry"]["content_hash"]:
        raise ws.WorkspaceError("The uploaded native source differs from the workspace ledger")
    identifier = str(uuid4())
    relative = ".forgepdm/drawings/" + identifier
    directory = ws._safe_path(value["root"], relative)
    directory.mkdir(parents=True, mode=0o700)
    return dict(
        baseline=baseline,
        root=str(value["root"]),
        directory=str(directory),
        relative=relative,
        path=str(path),
        revision_id=revision_id,
        item_id=item_id,
        actor_id=actor_id,
        revision=revision,
        source_created_at=source["created_at"],
        intent=dict(
            operation_id=identifier,
            source_dataset_id=baseline["dataset_id"],
            source_file_id=baseline["file_id"],
            source_content_hash=value["entry"]["content_hash"],
            expected_checkout_id=checkout["id"],
            expected_checkout_version=checkout["version"],
        ),
    )


def freeze(client, plan, pages):
    baseline = server_updates.baseline(client, plan["path"], plan["item_id"], plan["revision_id"])
    if baseline != plan["baseline"]:
        raise ws.WorkspaceError("The source snapshot changed during PDF export; review again")
    if not 1 <= len(pages) <= 32:
        raise ws.WorkspaceError("Select between 1 and 32 TechDraw pages")
    directory = ws._safe_path(Path(plan["root"]), plan["relative"])
    descriptors = []
    total = 0
    for index, page in enumerate(pages, 1):
        pdf = ws._safe_path(directory, "page_{:04d}.pdf".format(index))
        digest, size = ws.digest(pdf, client._checkpoint)
        if not 0 < size <= 25 * 1024**2:
            raise ws.WorkspaceError("Each drawing PDF must be between 1 byte and 25 MiB")
        with pdf.open("rb") as stream:
            head = stream.read(5)
            stream.seek(max(0, size - 1024))
            if head != b"%PDF-" or b"%%EOF" not in stream.read():
                raise ws.WorkspaceError(
                    "FreeCAD produced an incomplete PDF; no pages were uploaded"
                )
        total += size
        descriptors.append(
            dict(
                page_name=page["page_name"],
                page_label=page["page_label"],
                filename=page["filename"],
                content_hash=digest,
                byte_size=size,
            )
        )
        pdf.chmod(0o400)
    if total > 100 * 1024**2:
        raise ws.WorkspaceError("Drawing PDFs exceed the 100 MiB publication limit")
    bundle = directory / "publication.zip"
    with ZipFile(bundle, "x", compression=ZIP_STORED) as archive:
        for index in range(1, len(pages) + 1):
            client._checkpoint()
            name = "page_{:04d}.pdf".format(index)
            archive.write(directory / name, name)
    with bundle.open("rb") as stream:
        os.fsync(stream.fileno())
    bundle.chmod(0o400)
    bundle_hash, _ = ws.digest(bundle, client._checkpoint)
    intent = dict(plan["intent"], pages=descriptors)
    operation = dict(
        format=1,
        state="prepared",
        server_url=client.base_url,
        revision_id=plan["revision_id"],
        item_id=plan["item_id"],
        actor_id=plan["actor_id"],
        intent=intent,
        bundle_path=plan["relative"] + "/publication.zip",
        bundle_hash=bundle_hash,
    )
    with ws.locked(plan["root"], client.base_url):
        value, current = _load(
            client, plan["path"], plan["revision_id"], plan["item_id"], plan["actor_id"]
        )
        if current and current["state"] == "prepared":
            raise ws.WorkspaceError(
                "Another drawing publication is pending; exported PDFs were retained"
            )
        operation["source_path"] = value["entry"]["path"]
        ws._atomic_json(value["directory"] / JOURNAL, operation)
    return operation


def resume(client, path, revision_id, item_id, actor_id):
    value, operation = _load(client, path, revision_id, item_id, actor_id)
    if operation is None or operation["state"] == "acknowledged":
        return None
    intent = operation["intent"]
    result = client.drawing_publication_status(revision_id, intent["operation_id"])
    if result is None:
        bundle = ws._safe_path(value["root"], operation["bundle_path"])
        if ws.digest(bundle, client._checkpoint)[0] != operation["bundle_hash"]:
            raise ws.WorkspaceError(
                "Frozen PDF bundle changed; the pending publication was preserved"
            )
        result = client.upload_drawing_publication(revision_id, str(bundle), intent)
    if (
        result.get("operation_id") != intent["operation_id"]
        or result.get("revision_id") != revision_id
        or any(
            result.get(key) != intent[key]
            for key in ("source_dataset_id", "source_file_id", "source_content_hash")
        )
        or len(result.get("pages", [])) != len(intent["pages"])
    ):
        raise ws.WorkspaceError("Drawing publication response differs from its recorded intent")
    for expected, actual in zip(intent["pages"], result["pages"]):
        if any(expected[key] != actual.get(key) for key in expected):
            raise ws.WorkspaceError("Published PDF differs from its frozen page/hash")
    with ws.locked(value["root"], client.base_url):
        _, current = _load(client, path, revision_id, item_id, actor_id)
        if current["intent"] != intent:
            raise ws.WorkspaceError("Another local drawing operation replaced this journal")
        current.update(state="acknowledged", result=result)
        ws._atomic_json(value["directory"] / JOURNAL, current)
    return result


def abandon(client, path, revision_id, item_id, actor_id):
    value, operation = _load(client, path, revision_id, item_id, actor_id)
    if operation is None or operation["state"] != "prepared":
        return
    identifier = operation["intent"]["operation_id"]
    if client.drawing_publication_status(revision_id, identifier) is not None:
        raise ws.WorkspaceError("The previous drawing publication completed; recover it first")
    with ws.locked(value["root"], client.base_url):
        _, current = _load(client, path, revision_id, item_id, actor_id)
        if current != operation:
            raise ws.WorkspaceError("Pending drawing publication changed")
        journal = value["directory"] / JOURNAL
        destination = journal.with_name("drawing-publication-" + identifier + ".archived.json")
        if destination.exists():
            raise ws.WorkspaceError("Drawing recovery archive already exists")
        journal.rename(destination)
