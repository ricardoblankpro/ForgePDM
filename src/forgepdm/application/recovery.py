"""Read-only storage reconciliation. Candidates are never automatically deleted."""

from forgepdm.infrastructure.storage import StorageError


def recovery_report(database, storage):
    """Run offline for authoritative orphan results; live uploads can be in flight."""
    with database.connection() as connection:
        connection.execute("BEGIN")
        files = connection.execute(
            "SELECT id,storage_key,content_hash,byte_size FROM files"
        ).fetchall()
        unmanifested = [
            row[0]
            for row in connection.execute(
                "SELECT d.id FROM datasets d LEFT JOIN dataset_manifests m ON m.dataset_id=d.id "
                "WHERE d.dataset_type='native_cad' AND m.dataset_id IS NULL ORDER BY d.id"
            )
        ]
        operations = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("checkin_operations", "revision_operations")
        }
        integrity = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        foreign_keys = [list(row) for row in connection.execute("PRAGMA foreign_key_check")]
    broken = []
    for record in files:
        try:
            storage.verify(record["storage_key"], record["content_hash"], record["byte_size"])
        except (StorageError, ValueError, OSError) as error:
            broken.append({"file_id": record["id"], "reason": str(error)})
    known = {record["storage_key"] for record in files}
    candidates = []
    unsafe = []
    if storage.root.exists():
        import os

        for directory, dirs, names in os.walk(storage.root, followlinks=False):
            from pathlib import Path

            base = Path(directory)
            for name in dirs[:]:
                if (base / name).is_symlink():
                    unsafe.append(str((base / name).relative_to(storage.root)))
                    dirs.remove(name)
            for name in names:
                path = base / name
                relative = path.relative_to(storage.root).as_posix()
                if path.is_symlink():
                    unsafe.append(relative)
                elif relative not in known and (relative.startswith(("sha256/", ".staging/"))):
                    candidates.append(relative)
    return {
        "mode": "read_only",
        "requires_offline_review": True,
        "database_integrity": integrity,
        "foreign_key_errors": foreign_keys,
        "referenced_file_errors": broken,
        "unreferenced_candidates": sorted(candidates),
        "unsafe_links": sorted(unsafe),
        "native_datasets_without_manifest": unmanifested,
        "completed_operations": operations,
    }
