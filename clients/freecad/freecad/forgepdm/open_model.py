"""Selection and local-workspace validation for the native Open browser."""

import json
import os
from datetime import datetime
from pathlib import Path

from .workspace import MANIFEST, WorkspaceError


def validate_workspace(root, server):
    if not root:
        raise WorkspaceError("Choose a workspace once before opening CAD files.")
    path = Path(root).expanduser().absolute()
    if not path.is_dir() or not os.access(path, os.W_OK | os.X_OK):
        raise WorkspaceError(
            "The configured workspace is missing or not writable. Choose another folder."
        )
    admin = path / ".forgepdm"
    identity = admin / "identity.json"
    if admin.is_symlink() or identity.is_symlink():
        raise WorkspaceError("Workspace metadata must not be linked. Choose another folder.")
    if identity.exists():
        try:
            if json.loads(identity.read_text()).get("server_url") != server:
                raise WorkspaceError(
                    "This workspace belongs to another server. Choose another folder."
                )
        except (OSError, ValueError) as error:
            raise WorkspaceError(
                "Workspace identity needs inspection; choose another folder."
            ) from error
    # A configuration/document directory is not itself a workspace root.
    if (path / MANIFEST).exists() or any((parent / MANIFEST).exists() for parent in path.parents):
        raise WorkspaceError("Choose the workspace root, not a managed CAD configuration folder.")
    return str(path)


def snapshots(datasets):
    choices = [
        (dataset, record)
        for dataset in datasets
        if dataset["dataset_type"] == "native_cad"
        for record in dataset["files"]
    ]
    return sorted(
        choices,
        key=lambda choice: (choice[0]["created_at"], choice[0]["id"], choice[1]["id"]),
        reverse=True,
    )


def snapshot_label(dataset, record, newest=False):
    timestamp = (
        datetime.fromisoformat(dataset["created_at"]).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    )
    return "{}{} — {}".format(
        "Latest upload · " if newest else "", timestamp, record["original_filename"]
    )


def shortcut_items(client, source, entries, query="", number_series=None, limit=50, offset=0):
    """Resolve saved IDs through authorized HTTP; never use saved catalog labels."""
    if source == "checkouts":
        checkouts = []
        scan_offset = 0
        while True:
            page = client.my_checkouts(limit=100, offset=scan_offset)
            checkouts.extend(page["items"])
            if not page["has_more"] or len(checkouts) >= 1000:
                truncated = page["has_more"]
                break
            scan_offset += page["limit"]
        entries = [
            {
                "item_id": entry["item_id"],
                "revision_id": entry["revision_id"],
                "checkout_status": entry["status"],
            }
            for entry in checkouts
        ]
    else:
        truncated = False
        entries = [
            {"item_id": entry} if isinstance(entry, str) else dict(entry) for entry in entries
        ]
    rows, unavailable = [], 0
    for entry in entries:
        try:
            item = client.get_item(entry["item_id"])
            revision = client.get_revision(entry.get("revision_id") or item["current_revision_id"])
        except Exception as error:
            if getattr(error, "status", None) in (403, 404):
                unavailable += 1
                continue
            raise
        if revision["item_id"] != item["id"]:
            raise ValueError("Saved shortcut belongs to a different item; it was preserved")
        number = item["number"]
        description = revision.get("description_record", {}).get("description") or item.get(
            "description", ""
        )
        if number_series and not number.startswith(number_series):
            continue
        if query.casefold() not in " ".join([number, item["name"], description]).casefold():
            continue
        row = {
            **item,
            "revision_label": revision["label"],
            "lifecycle_state": revision["lifecycle_state"],
            "revision_description": description,
        }
        if source in ("recent", "checkouts"):
            row["preferred_revision"] = revision
        if source == "recent":
            row["preferred_dataset_id"] = entry["dataset_id"]
            row["preferred_file_id"] = entry["file_id"]
        if source == "checkouts":
            row["checkout_status"] = entry["checkout_status"]
        rows.append(row)
    return {
        "items": rows[offset : offset + limit],
        "offset": offset,
        "limit": limit,
        "has_more": len(rows) > offset + limit,
        "unavailable": unavailable,
        "truncated": truncated,
    }
