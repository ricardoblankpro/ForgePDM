"""Read-only comparison of managed CAD snapshots with the server."""

import json

from . import part_checkin, workspace


def baseline(client, path, item_id, revision_id):
    value = workspace.binding(path, client.base_url)
    entry = value["entry"]
    if entry["item_id"] != item_id or entry["revision_id"] != revision_id:
        raise workspace.WorkspaceError("Document identity differs from its workspace ledger")
    journal = value["directory"] / part_checkin.JOURNAL
    if journal.is_symlink() or (
        journal.exists() and json.loads(journal.read_text()).get("state") != "acknowledged"
    ):
        raise workspace.WorkspaceError("Resolve the pending Check In before updating from server")
    digest = workspace.digest(path, client._checkpoint)[0]
    if digest != entry["working_hash"]:
        raise workspace.WorkspaceError(
            "Saved local changes have not been uploaded. Upload/check in or preserve them first."
        )
    return {
        "root": str(value["root"]),
        "dataset_id": entry["dataset_id"],
        "file_id": entry["file_id"],
        "hash": digest,
    }


def latest_snapshot(client, item_id, revision_id):
    revision = client.get_revision(revision_id)
    if revision["item_id"] != item_id:
        raise workspace.WorkspaceError("Server revision belongs to a different item")
    snapshots = [
        (dataset, record)
        for dataset in client.list_datasets(revision_id)
        if dataset["dataset_type"] == "native_cad"
        for record in dataset["files"]
    ]
    if not snapshots:
        raise workspace.WorkspaceError("This revision has no uploaded native CAD snapshot")
    dataset, record = max(
        snapshots, key=lambda pair: (pair[0]["created_at"], pair[0]["id"], pair[1]["id"])
    )
    return revision, dataset, record


def inspect(client, path, item_id, revision_id):
    original = baseline(client, path, item_id, revision_id)
    revision, dataset, record = latest_snapshot(client, item_id, revision_id)
    return {
        "baseline": original,
        "revision": revision,
        "dataset": dataset,
        "file": record,
        "changed": (dataset["id"], record["id"]) != (original["dataset_id"], original["file_id"]),
        "newer": client.newer_revisions(item_id, revision_id),
    }


def prepare_components(client, path, item_id, revision_id, references):
    original = baseline(client, path, item_id, revision_id)
    identities = {(ref["target_item_id"], ref["target_revision_id"]) for ref in references}
    if len(identities) != 1:
        raise workspace.WorkspaceError("Update one component item/revision at a time")
    component_item, component_revision = next(iter(identities))
    revision, dataset, record = latest_snapshot(client, component_item, component_revision)
    if revision["lifecycle_state"] == "obsolete":
        raise workspace.WorkspaceError("An obsolete component revision cannot be adopted")
    pins = workspace.bind_references(client, references)
    changed = [
        pin["object_name"]
        for pin in pins
        if (pin["target_dataset_id"], pin["target_file_id"]) != (dataset["id"], record["id"])
    ]
    return dict(
        baseline=original, revision=revision, dataset=dataset, file=record, pins=pins, names=changed
    )
