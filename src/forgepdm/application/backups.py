"""Consistent SQLite/blob backups and isolated, non-destructive restore drills.

Online capture relies on promotion before commit and immutable, non-deleted blobs.
Any future garbage collector must coordinate with this protocol (ADR-024).
"""

import hashlib
import json
import os
import platform
import shutil
import sqlite3
import stat
import tempfile
import time
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from forgepdm import __version__
from forgepdm.infrastructure.database import MIGRATIONS
from forgepdm.infrastructure.storage import CHUNK_SIZE, FileStorage

FORMAT_VERSION = 1
DATABASE_NAME = "database.sqlite3"
MANIFEST_NAME = "manifest.json"


class BackupError(ValueError):
    """A backup or restore could not be completed and verified."""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _plain_path(value):
    path = Path(os.path.abspath(value))
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise BackupError("symlinks are not supported in backup/restore paths")
    return path


def _disjoint(first, second):
    if first == second or first in second.parents or second in first.parents:
        raise BackupError("backup, restore and live data paths must not overlap")


def _private_directory(path):
    path = _plain_path(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_json(path, value):
    path = _plain_path(path)
    descriptor, name = tempfile.mkstemp(prefix=".json-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        _sync_directory(path.parent)
    finally:
        Path(name).unlink(missing_ok=True)


@contextmanager
def _new_bundle(destination):
    """Reserve a new destination, publish only a complete verified directory."""
    destination = _plain_path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination.mkdir(mode=0o700, exist_ok=False)
    published = False
    try:
        with tempfile.TemporaryDirectory(prefix=".partial-", dir=destination.parent) as name:
            staging = Path(name)
            yield staging
            for directory, _, _ in os.walk(staging, topdown=False):
                _sync_directory(directory)
            os.rename(staging, destination)
            published = True
            _sync_directory(destination.parent)
    finally:
        if not published:
            destination.rmdir()


def _digest(path):
    path = _plain_path(path)
    if not stat.S_ISREG(path.stat().st_mode):
        raise BackupError("backup inputs must be regular files")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(CHUNK_SIZE):
            digest.update(chunk)
            size += len(chunk)
    return {"sha256": digest.hexdigest(), "bytes": size}


def _copy_file(source, target, expected):
    source = _plain_path(source)
    if not stat.S_ISREG(source.stat().st_mode):
        raise BackupError("backup inputs must be regular files")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    digest, size = hashlib.sha256(), 0
    with source.open("rb") as reader, target.open("xb") as writer:
        target.chmod(0o600)
        while chunk := reader.read(CHUNK_SIZE):
            digest.update(chunk)
            size += len(chunk)
            writer.write(chunk)
        writer.flush()
        os.fsync(writer.fileno())
    if expected != {"sha256": digest.hexdigest(), "bytes": size}:
        raise BackupError("file hash/size mismatch while copying")


def _read_database(path):
    # immutable=1 is safe only for our closed, standalone snapshot, never a live DB.
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as c:
        c.row_factory = sqlite3.Row
        if [r[0] for r in c.execute("PRAGMA integrity_check")] != ["ok"]:
            raise BackupError("SQLite integrity check failed")
        if c.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise BackupError("SQLite foreign key check failed")
        versions = [r[0] for r in c.execute("SELECT version FROM schema_version ORDER BY version")]
        known = [version for version, _ in MIGRATIONS]
        if not versions or versions != known[: len(versions)]:
            raise BackupError("unsupported database schema; use a compatible backend")
        tables = [
            r[0]
            for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        counts = {}
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            counts[table] = c.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]
        files = {}
        for row in c.execute("SELECT storage_key,content_hash,byte_size FROM files"):
            if not isinstance(row["content_hash"], str):
                raise BackupError("invalid database blob hash")
            key = FileStorage.storage_key(row["content_hash"])
            if (
                row["storage_key"] != key
                or type(row["byte_size"]) is not int
                or row["byte_size"] <= 0
            ):
                raise BackupError("invalid database blob identity")
            record = {"sha256": row["content_hash"], "bytes": row["byte_size"]}
            if key in files and files[key] != record:
                raise BackupError("conflicting blob identities")
            files[key] = record
    return {"schema_versions": versions, "table_counts": counts, "files": files}


def _snapshot(source, destination, timeout):
    source = _plain_path(source)
    if not source.is_file():
        raise BackupError("source database does not exist")
    started = time.monotonic()

    def progress(status, remaining, total):
        if time.monotonic() - started > timeout:
            raise BackupError("SQLite backup timed out")

    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as reader:
        with closing(sqlite3.connect(destination)) as writer:
            destination.chmod(0o600)
            reader.backup(writer, pages=256, progress=progress, sleep=0.05)
            writer.execute("PRAGMA journal_mode=DELETE")
    with destination.open("rb") as stream:
        os.fsync(stream.fileno())


def _manifest(path):
    path = _plain_path(path)
    if path.stat().st_size > 32 * 1024 * 1024:
        raise BackupError("backup manifest is too large")
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(value, dict)
        or type(value.get("format_version")) is not int
        or value["format_version"] != FORMAT_VERSION
    ):
        raise BackupError("unsupported backup format")
    if value.get("database_engine") != "sqlite":
        raise BackupError("unsupported backup database engine")
    for name in ("created_at", "backend_version", "python_version", "sqlite_version"):
        if not isinstance(value.get(name), str) or not value[name]:
            raise BackupError("missing or invalid backup metadata")
    return value


def _verify_backup(bundle):
    """Hash every referenced file and validate the closed DB without migrations."""
    bundle = _plain_path(bundle)
    manifest = _manifest(bundle / MANIFEST_NAME)
    database = bundle / DATABASE_NAME
    if _digest(database) != manifest.get("database"):
        raise BackupError("database hash/size mismatch")
    evidence = _read_database(database)
    if any(manifest.get(key) != value for key, value in evidence.items()):
        raise BackupError("manifest does not match database contents")
    expected = {DATABASE_NAME, MANIFEST_NAME}
    for key, identity in evidence["files"].items():
        relative = "files/" + key
        expected.add(relative)
        if _digest(bundle / relative) != identity:
            raise BackupError("stored blob hash/size mismatch")
    actual = set()
    for directory, directories, files in os.walk(bundle, followlinks=False):
        base = Path(directory)
        for name in directories:
            _plain_path(base / name)
        for name in files:
            path = _plain_path(base / name)
            actual.add(path.relative_to(bundle).as_posix())
    if actual != expected:
        raise BackupError("unexpected or missing files in backup bundle")
    report = {
        "verified": True,
        "backup": str(bundle),
        "created_at": manifest["created_at"],
        "backend_version": manifest["backend_version"],
        "schema_version": evidence["schema_versions"][-1],
        "table_counts": evidence["table_counts"],
        "unique_blobs": len(evidence["files"]),
        "file_records": evidence["table_counts"]["files"],
        "blob_bytes": sum(value["bytes"] for value in evidence["files"].values()),
    }
    return report, manifest


def verify_backup(bundle):
    """Verify a complete bundle without initializing or migrating its database."""
    return _verify_backup(bundle)[0]


def create_backup(database, storage, destination, *, timeout=120):
    """Snapshot metadata first, then copy only its committed immutable blobs."""
    root = _plain_path(destination)
    source = _plain_path(database.path)
    blobs = _plain_path(storage.root)
    _disjoint(root, source)
    _disjoint(root, blobs)
    root = _private_directory(root)
    name = datetime.now(timezone.utc).strftime("backup-%Y%m%dT%H%M%S.%fZ-") + uuid4().hex[:8]
    target = root / name
    with _new_bundle(target) as staging:
        snapshot = staging / DATABASE_NAME
        snapshot_started = _now()
        _snapshot(source, snapshot, timeout)
        snapshot_finished = _now()
        evidence = _read_database(snapshot)
        needed = sum(value["bytes"] for value in evidence["files"].values())
        if shutil.disk_usage(root).free < needed + 64 * 1024 * 1024:
            raise BackupError("insufficient free space for backup plus 64 MiB reserve")
        for key, identity in evidence["files"].items():
            _copy_file(blobs / key, staging / "files" / key, identity)
        _write_json(
            staging / MANIFEST_NAME,
            {
                "format_version": FORMAT_VERSION,
                "database_engine": "sqlite",
                "created_at": _now(),
                "snapshot_started_at": snapshot_started,
                "snapshot_finished_at": snapshot_finished,
                "backend_version": __version__,
                "python_version": platform.python_version(),
                "sqlite_version": sqlite3.sqlite_version,
                "database": _digest(snapshot),
                **evidence,
            },
        )
        report = verify_backup(staging)
    return {**report, "backup": str(target)}


def restore_backup(bundle, destination, *, live_database, live_storage):
    """Restore only to a new, separate directory; never replace a live root."""
    bundle, target = _plain_path(bundle), _plain_path(destination)
    for source in (bundle, _plain_path(live_database), _plain_path(live_storage)):
        _disjoint(target, source)
    report, manifest = _verify_backup(bundle)
    # Keep the manifest verified above in memory throughout copying.
    required = manifest["database"]["bytes"] + report["blob_bytes"] + 64 * 1024 * 1024
    with _new_bundle(target) as staging:
        if shutil.disk_usage(staging).free < required:
            raise BackupError("insufficient free space for restore plus 64 MiB reserve")
        _copy_file(bundle / DATABASE_NAME, staging / DATABASE_NAME, manifest["database"])
        for key, identity in manifest["files"].items():
            _copy_file(bundle / "files" / key, staging / "files" / key, identity)
        _write_json(staging / MANIFEST_NAME, manifest)
        verify_backup(staging)
    return {**report, "restored_to": str(target)}


def latest_backup(root):
    root = _plain_path(root)
    candidates = sorted(path for path in root.glob("backup-*") if (path / MANIFEST_NAME).is_file())
    if not candidates:
        raise BackupError("no completed backup found")
    # A corrupt newest backup fails visibly; do not silently fall back to old data.
    return candidates[-1]


def drill_backup(bundle, scratch_root, *, live_database, live_storage):
    bundle, scratch = _plain_path(bundle), _plain_path(scratch_root)
    for source in (bundle.parent, _plain_path(live_database), _plain_path(live_storage)):
        _disjoint(scratch, source)
    started = time.monotonic()
    scratch = _private_directory(scratch)
    with tempfile.TemporaryDirectory(prefix="drill-", dir=scratch) as name:
        target = Path(name) / "restored"
        result = restore_backup(
            bundle, target, live_database=live_database, live_storage=live_storage
        )
    result.pop("restored_to")
    return {
        **result,
        "drill_verified": True,
        "duration_seconds": round(time.monotonic() - started, 3),
    }


@contextmanager
def recorded_operation(root, operation, *, live_database, live_storage):
    """Serialize scheduled/manual operations per root and retain failure evidence."""
    try:
        import fcntl
    except ImportError as error:
        raise BackupError("scheduled backup locking currently requires Linux/Unix") from error

    root = _plain_path(root)
    for source in (live_database, live_storage):
        _disjoint(root, _plain_path(source))
    root = _private_directory(root)
    lock = _plain_path(root / ".automation.lock")
    descriptor = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise BackupError("another backup/drill operation is already running") from error
        status_path = _plain_path(root / f"{operation}-status.json")
        try:
            previous = json.loads(status_path.read_text()) if status_path.exists() else {}
        except (ValueError, OSError):
            previous = {}
        if not isinstance(previous, dict):
            previous = {}
        status = {
            "operation": operation,
            "started_at": _now(),
            "last_success": previous.get("last_success"),
        }
        result = {}
        _write_json(status_path, {**status, "ok": False, "state": "running"})
        try:
            yield result
        except Exception as error:
            _write_json(
                status_path, {**status, "ok": False, "finished_at": _now(), "error": str(error)}
            )
            raise
        else:
            finished = _now()
            _write_json(
                status_path,
                {
                    **status,
                    "ok": True,
                    "finished_at": finished,
                    "last_success": {"at": finished, **result},
                },
            )
    finally:
        os.close(descriptor)


def backup_status(root, *, max_age_hours=3, max_drill_age_hours=48):
    root = _plain_path(root)
    reports, problems = {}, []
    for operation, limit in (("backup", max_age_hours), ("drill", max_drill_age_hours)):
        path = _plain_path(root / f"{operation}-status.json")
        try:
            status = json.loads(path.read_text())
            success = status.get("last_success") or {}
            at = datetime.fromisoformat(success["at"])
            age = (datetime.now(timezone.utc) - at).total_seconds() / 3600
            if not status.get("ok") or not 0 <= age <= limit:
                problems.append(f"{operation} failed or is stale")
            bundle = _plain_path(success["backup"])
            if not (bundle / MANIFEST_NAME).is_file():
                problems.append(f"{operation} recovery point is missing")
            reports[operation] = status
        except (OSError, ValueError, KeyError, TypeError):
            problems.append(f"{operation} has no readable success report")
    return {"ok": not problems, "problems": problems, **reports}
