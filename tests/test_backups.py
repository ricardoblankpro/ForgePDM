"""Backups preserve exact history and fail closed without touching live data."""

import importlib.util
import json
import sqlite3
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import TEST_PASSWORD, create_item
from fastapi.testclient import TestClient
from test_manifests import edge, service, upload

from forgepdm.application import backups
from forgepdm.application.backups import BackupError
from forgepdm.domain.entities import LifecycleState
from forgepdm.infrastructure.database import Database


@pytest.fixture
def saved(backend, tmp_path):
    b = backend
    child, child_data, child_file = upload(b)
    parent, data, file = upload(b, create_item(b, kind="assembly"))
    manifest = service(b).attach(
        b.users["editor"], data.id, file.id, [edge(child, child_data, child_file)]
    )
    b.bom.replace_bom(
        b.users["editor"],
        parent.current_revision_id,
        [{"component_revision_id": child.current_revision_id, "quantity": "2.5", "position": 1}],
    )
    b.revisions.check_in(b.users["editor"], child.current_revision_id, "Historical CAD")
    b.revisions.transition_lifecycle(
        b.users["editor"], child.current_revision_id, LifecycleState.RELEASED
    )
    b.revisions.create_next_revision(b.users["editor"], child.id, "New revision")
    report = backups.create_backup(b.database, b.storage, tmp_path / "backups")
    return b, Path(report["backup"]), (parent, child_data, child_file, data, manifest)


def live(b):
    return {"live_database": b.database.path, "live_storage": b.storage.root}


def rows(database):
    with database.connection() as c:
        tables = [
            r[0]
            for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        return {
            table: sorted([tuple(r) for r in c.execute(f'SELECT * FROM "{table}"')], key=repr)
            for table in tables
        }


def test_restored_api_keeps_historical_bom_file_manifest_permissions_and_all_tables(
    saved, tmp_path, monkeypatch
):
    b, bundle, (parent, child_data, child_file, data, manifest) = saved
    before = rows(b.database)
    result = backups.restore_backup(bundle, tmp_path / "restored", **live(b))
    restored = Path(result["restored_to"])
    assert rows(Database(restored / "database.sqlite3")) == before
    # Start API only against the restored data, never the source.
    monkeypatch.setenv("FORGEPDM_FILE_ROOT", str(restored / "files"))
    from forgepdm.main import create_app

    with TestClient(create_app(restored / "database.sqlite3")) as client:
        assert client.get("/health").json()["status"] == "ok"
        assert client.get(f"/api/v1/files/{child_file.id}").status_code == 401
        response = client.post(
            "/api/v1/auth/login", json={"username": "viewer", "password": TEST_PASSWORD}
        )
        assert response.status_code == 200
        client.headers["Authorization"] = "Bearer " + response.json()["access_token"]
        response = client.get(f"/api/v1/revisions/{parent.current_revision_id}/bom-report")
        assert response.status_code == 200
        component = response.json()["views"]["direct"][0]
        assert component["component_revision_id"] == child_data.revision_id
        assert component["quantity"] == "2.5"
        assert client.get(f"/api/v1/datasets/{data.id}/manifest").json() == manifest
        assert client.get(f"/api/v1/files/{child_file.id}").content == b"native-bytes"
    assert rows(b.database) == before


def test_deduplication_drill_permissions_and_source_unchanged(saved, tmp_path):
    b, bundle, _ = saved
    before = rows(b.database)
    report = backups.verify_backup(bundle)
    assert report["file_records"] == 2
    assert report["unique_blobs"] == 1
    assert stat.S_IMODE(bundle.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in bundle.rglob("*") if p.is_file())
    drill = backups.drill_backup(bundle, tmp_path / "scratch", **live(b))
    assert drill["drill_verified"]
    assert list((tmp_path / "scratch").iterdir()) == []
    assert rows(b.database) == before


def test_online_wal_snapshot_ignores_subsequent_commits_and_uncommitted_work(
    backend, tmp_path, monkeypatch
):
    b = backend
    upload(b)
    with b.database.connection() as c:
        c.execute("BEGIN IMMEDIATE")
        c.execute("UPDATE users SET display_name='Uncommitted' WHERE username='viewer'")
        root = tmp_path / "backups"
        report = backups.create_backup(b.database, b.storage, root)
        c.rollback()
    original_copy = backups._copy_file
    committed = []

    def copy_and_commit(*args):
        if not committed:
            with b.database.transaction() as c:
                c.execute("UPDATE users SET display_name='After snapshot' WHERE username='viewer'")
            committed.append(True)
        return original_copy(*args)

    monkeypatch.setattr(backups, "_copy_file", copy_and_commit)
    next_report = backups.create_backup(b.database, b.storage, root)
    for result in (report, next_report):
        with sqlite3.connect(Path(result["backup"]) / "database.sqlite3") as c:
            assert (
                c.execute("SELECT display_name FROM users WHERE username='viewer'").fetchone()[0]
                == "Viewer"
            )
    assert committed


@pytest.mark.parametrize(
    "damage",
    [
        "database",
        "blob",
        "missing",
        "manifest",
        "extra",
        "symlink",
        "parent-symlink",
        "schema",
        "foreign-key",
    ],
)
def test_damaged_backups_fail_without_publishing_restore(saved, tmp_path, damage):
    b, bundle, _ = saved
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    key = next(iter(manifest["files"]))
    blob = bundle / "files" / key
    if damage == "database":
        with (bundle / "database.sqlite3").open("ab") as stream:
            stream.write(b"damage")
    elif damage == "blob":
        blob.write_bytes(b"changed")
    elif damage == "missing":
        blob.unlink()
    elif damage == "manifest":
        manifest["files"] = {"../../secret": {"sha256": "a" * 64, "bytes": 1}}
        manifest_path.write_text(json.dumps(manifest))
    elif damage == "extra":
        (bundle / "extra").write_text("untracked")
    elif damage == "symlink":
        original = tmp_path / "original"
        blob.rename(original)
        blob.symlink_to(original)
    elif damage == "parent-symlink":
        original = tmp_path / "original"
        blob.parent.rename(original)
        blob.parent.symlink_to(original, target_is_directory=True)
    else:
        with sqlite3.connect(bundle / "database.sqlite3") as c:
            if damage == "schema":
                c.execute("DELETE FROM schema_version WHERE version=17")
            else:
                c.execute("UPDATE dataset_files SET file_id='missing'")
        manifest["database"] = backups._digest(bundle / "database.sqlite3")
        manifest_path.write_text(json.dumps(manifest))
    target = tmp_path / "restored"
    before = rows(b.database)
    with pytest.raises((BackupError, OSError)):
        backups.restore_backup(bundle, target, **live(b))
    assert not target.exists()
    assert rows(b.database) == before


@pytest.mark.parametrize(
    "existing",
    ["empty", "data", "symlink", "live-db-parent", "live-storage", "inside-live-storage", "bundle"],
)
def test_restore_refuses_existing_and_overlapping_destinations(saved, tmp_path, existing):
    b, bundle, _ = saved
    target = tmp_path / "target"
    if existing in {"empty", "data"}:
        target.mkdir()
        if existing == "data":
            (target / "important").write_text("keep")
    elif existing == "symlink":
        target.symlink_to(bundle, target_is_directory=True)
    else:
        target = {
            "live-db-parent": b.database.path.parent,
            "live-storage": b.storage.root,
            "inside-live-storage": b.storage.root / "nested",
            "bundle": bundle,
        }[existing]
    before = rows(b.database)
    with pytest.raises((BackupError, FileExistsError)):
        backups.restore_backup(bundle, target, **live(b))
    assert rows(b.database) == before
    if existing == "data":
        assert (target / "important").read_text() == "keep"


def test_backup_failure_missing_blob_and_interrupted_restore_leave_no_complete_result(
    saved, tmp_path, monkeypatch
):
    b, bundle, _ = saved
    copy = backups._copy_file

    def fail(*args):
        copy(*args)
        raise OSError("simulated full disk")

    monkeypatch.setattr(backups, "_copy_file", fail)
    root = tmp_path / "failure"
    with pytest.raises(OSError, match="full disk"):
        backups.create_backup(b.database, b.storage, root)
    assert list(root.iterdir()) == []
    with pytest.raises(OSError, match="full disk"):
        backups.restore_backup(bundle, tmp_path / "restored", **live(b))
    assert not (tmp_path / "restored").exists()
    monkeypatch.setattr(backups, "_copy_file", copy)
    next(b.storage.root.rglob("[0-9a-f]" * 64)).unlink()
    with pytest.raises(FileNotFoundError):
        backups.create_backup(b.database, b.storage, root)
    assert list(root.iterdir()) == []


def test_recorded_success_failure_lock_status_age_and_latest(saved, tmp_path):
    b, bundle, _ = saved
    root = bundle.parent
    assert not backups.backup_status(root)["ok"]
    for operation in ("backup", "drill"):
        with backups.recorded_operation(root, operation, **live(b)) as report:
            report.update(backups.verify_backup(bundle))
            with pytest.raises(BackupError, match="already running"):
                with backups.recorded_operation(root, operation, **live(b)):
                    pass
    assert backups.backup_status(root)["ok"]
    with pytest.raises(OSError):
        with backups.recorded_operation(root, "backup", **live(b)):
            raise OSError("disk unavailable")
    status = backups.backup_status(root)
    assert not status["ok"]
    assert status["backup"]["last_success"]["verified"]
    assert status["backup"]["error"] == "disk unavailable"
    (root / "backup-zz-incomplete").mkdir()
    assert backups.latest_backup(root) == bundle
    path = root / "drill-status.json"
    state = json.loads(path.read_text())
    state["last_success"]["at"] = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    path.write_text(json.dumps(state))
    assert "drill failed or is stale" in backups.backup_status(root)["problems"]


def test_missing_database_never_created_and_overlap_never_changes_live_directory(backend, tmp_path):
    b = backend
    missing = tmp_path / "missing.sqlite3"
    with pytest.raises(BackupError, match="does not exist"):
        backups.create_backup(Database(missing), b.storage, tmp_path / "backups")
    assert not missing.exists()
    mode = b.storage.root.parent.stat().st_mode
    with pytest.raises(BackupError, match="overlap"):
        with backups.recorded_operation(b.storage.root.parent, "backup", **live(b)):
            pass
    assert b.storage.root.parent.stat().st_mode == mode


def test_full_disk_timeout_and_unsafe_source_do_not_publish(backend, tmp_path, monkeypatch):
    b = backend
    upload(b)
    root = tmp_path / "backups"
    usage = backups.shutil.disk_usage
    monkeypatch.setattr(backups.shutil, "disk_usage", lambda path: type(usage(path))(100, 99, 1))
    with pytest.raises(BackupError, match="free space"):
        backups.create_backup(b.database, b.storage, root)
    assert list(root.iterdir()) == []
    monkeypatch.setattr(backups.shutil, "disk_usage", usage)
    with pytest.raises(BackupError, match="timed out"):
        backups.create_backup(b.database, b.storage, root, timeout=-1)
    assert list(root.iterdir()) == []
    blob = next(b.storage.root.rglob("[0-9a-f]" * 64))
    original = tmp_path / "outside"
    blob.rename(original)
    blob.symlink_to(original)
    with pytest.raises(BackupError, match="symlinks"):
        backups.create_backup(b.database, b.storage, root)
    assert list(root.iterdir()) == []


def test_restore_uses_verified_manifest_even_if_input_changes_after_verification(
    saved, tmp_path, monkeypatch
):
    b, bundle, _ = saved
    original_copy = backups._copy_file
    manifest_path = bundle / "manifest.json"
    trusted = json.loads(manifest_path.read_text())

    def tamper_then_copy(*args):
        changed = {**trusted, "files": {"../../escape": {"bytes": 1, "sha256": "a" * 64}}}
        manifest_path.write_text(json.dumps(changed))
        return original_copy(*args)

    monkeypatch.setattr(backups, "_copy_file", tamper_then_copy)
    target = tmp_path / "restored"
    backups.restore_backup(bundle, target, **live(b))
    assert json.loads((target / "manifest.json").read_text()) == trusted
    assert not (tmp_path / "escape").exists()


def test_installer_quotes_paths_and_refuses_unmanaged_units(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "backup_installer", Path(__file__).parents[1] / "tools/install_backup_automation.py"
    )
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    definitions = installer.units(
        '/a path/"$x%/forgepdm', "/data/db", "/data/files", "/backups", "/scratch"
    )
    assert 'ExecStart="/a path/\\"$$x%%/forgepdm"' in definitions["forgepdm-backup.service"]
    assert "OnCalendar=hourly" in definitions["forgepdm-backup.timer"]
    installer.install(definitions, tmp_path)
    installer.install(definitions, tmp_path)
    (tmp_path / "forgepdm-backup.service").write_text("unmanaged")
    with pytest.raises(ValueError, match="unmanaged"):
        installer.install(definitions, tmp_path)
    assert (tmp_path / "forgepdm-backup.service").read_text() == "unmanaged"


def test_cli_backup_drill_status_and_failure_exit(backend, tmp_path, monkeypatch, capsys):
    from forgepdm.cli import main

    b = backend
    upload(b)
    monkeypatch.setenv("FORGEPDM_DATABASE", str(b.database.path))
    monkeypatch.setenv("FORGEPDM_FILE_ROOT", str(b.storage.root))
    root = tmp_path / "backups"

    def run(*args):
        monkeypatch.setattr("sys.argv", ["forgepdm", *map(str, args)])
        main()
        return json.loads(capsys.readouterr().out)

    assert run("backup-create", "--destination", root)["verified"]
    assert run("backup-drill", root, "--latest", "--scratch-root", tmp_path / "scratch")[
        "drill_verified"
    ]
    assert run("backup-status", root)["ok"]
    bundle = backups.latest_backup(root)
    assert run("backup-verify", bundle)["verified"]
    assert run("backup-restore", bundle, "--destination", tmp_path / "restored")["restored_to"]
    with pytest.raises(SystemExit) as error:
        run("backup-restore", bundle, "--destination", tmp_path / "restored")
    assert error.value.code == 1
    capsys.readouterr()
    with pytest.raises(SystemExit) as error:
        run("backup-status", tmp_path / "no-backups")
    assert error.value.code == 1
