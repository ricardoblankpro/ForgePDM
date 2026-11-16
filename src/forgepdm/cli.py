"""Local administration commands for bootstrapping the development database."""

import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone
from getpass import getpass
from pathlib import Path
from uuid import uuid4

from forgepdm.application.auth import MIN_PASSWORD_LENGTH, hash_password
from forgepdm.application.standard_library import enroll_reader
from forgepdm.infrastructure.database import Database


def main() -> None:
    parser = argparse.ArgumentParser(prog="forgepdm")
    commands = parser.add_subparsers(dest="command", required=True)
    add_user = commands.add_parser("create-user", help="create a local development user")
    add_user.add_argument("username")
    add_user.add_argument("display_name")
    add_user.add_argument("--role", choices=("admin", "user"), default="user")
    set_password = commands.add_parser("set-password", help="set or reset a user's password")
    set_password.add_argument("username")
    set_role = commands.add_parser("set-role", help="set a user's global role")
    set_role.add_argument("username")
    set_role.add_argument("role", choices=("admin", "user"))
    add_project = commands.add_parser("create-project", help="create a project")
    add_project.add_argument("project_number")
    add_project.add_argument("name")
    add_project.add_argument("--owner-id")
    grant = commands.add_parser("grant-project", help="grant a user project access")
    grant.add_argument("project_id")
    grant.add_argument("user_id")
    grant.add_argument("--role", choices=("owner", "editor", "viewer"), default="editor")
    commands.add_parser(
        "recovery-report",
        help="read-only database/blob integrity and orphan diagnostics; stop uploads first",
    )
    backup = commands.add_parser(
        "backup-create", help="create and verify an online SQLite/blob backup"
    )
    backup.add_argument(
        "--destination", type=Path, required=True, help="backup repository directory"
    )
    verify = commands.add_parser(
        "backup-verify", help="verify a completed backup without changing it"
    )
    verify.add_argument("backup", type=Path)
    restore = commands.add_parser(
        "backup-restore", help="restore into a NEW directory, never live data"
    )
    restore.add_argument("backup", type=Path)
    restore.add_argument("--destination", type=Path, required=True)
    drill = commands.add_parser(
        "backup-drill", help="restore and verify in disposable isolated storage"
    )
    drill.add_argument("backup", type=Path)
    drill.add_argument(
        "--latest", action="store_true", help="select newest completed backup in repository"
    )
    drill.add_argument("--scratch-root", type=Path, required=True)
    status = commands.add_parser(
        "backup-status", help="report missing, stale or failed backup/drill runs"
    )
    status.add_argument("backup_root", type=Path)
    status.add_argument("--max-age-hours", type=float, default=3)
    status.add_argument("--max-drill-age-hours", type=float, default=48)
    args = parser.parse_args()
    path = Path(os.environ.get("FORGEPDM_DATABASE", "var/forgepdm.sqlite3"))
    database = Database(path)
    if args.command.startswith("backup-"):
        from forgepdm.application import backups
        from forgepdm.infrastructure.storage import FileStorage

        storage = FileStorage(Path(os.environ.get("FORGEPDM_FILE_ROOT", "var/files")))
        live = {"live_database": path, "live_storage": storage.root}
        try:
            if args.command == "backup-create":
                with backups.recorded_operation(args.destination, "backup", **live) as report:
                    report.update(backups.create_backup(database, storage, args.destination))
            elif args.command == "backup-verify":
                report = backups.verify_backup(args.backup)
            elif args.command == "backup-restore":
                report = backups.restore_backup(args.backup, args.destination, **live)
            elif args.command == "backup-drill":
                root = args.backup if args.latest else args.backup.parent
                with backups.recorded_operation(root, "drill", **live) as report:
                    bundle = backups.latest_backup(args.backup) if args.latest else args.backup
                    report.update(backups.drill_backup(bundle, args.scratch_root, **live))
            else:
                report = backups.backup_status(
                    args.backup_root,
                    max_age_hours=args.max_age_hours,
                    max_drill_age_hours=args.max_drill_age_hours,
                )
                print(json.dumps(report, indent=2))
                if not report["ok"]:
                    raise SystemExit(1)
                return
        except (ValueError, OSError, sqlite3.Error) as error:
            parser.exit(1, f"Backup operation failed: {error}\n")
        print(json.dumps(report, indent=2))
        return
    if args.command == "recovery-report":
        from forgepdm.application.recovery import recovery_report
        from forgepdm.infrastructure.storage import FileStorage

        if not path.is_file():
            parser.error("database does not exist")
        print(
            json.dumps(
                recovery_report(
                    database, FileStorage(Path(os.environ.get("FORGEPDM_FILE_ROOT", "var/files")))
                ),
                indent=2,
            )
        )
        return
    database.initialize()
    if args.command == "create-user":
        args.username = args.username.strip()
        args.display_name = args.display_name.strip()
        if not args.username or not args.display_name:
            parser.error("username and display name must not be empty")
    elif args.command in {"set-password", "set-role"}:
        args.username = args.username.strip()
    if args.command in {"create-user", "set-password"}:
        password = getpass(f"Password (at least {MIN_PASSWORD_LENGTH} characters): ")
        confirmation = getpass("Confirm password: ")
        if password != confirmation:
            parser.error("passwords do not match")
        try:
            password_hash = hash_password(password)
        except ValueError as error:
            parser.error(str(error))
    try:
        with database.transaction() as connection:
            now = datetime.now(timezone.utc).isoformat()
            if args.command == "create-user":
                identifier = str(uuid4())
                connection.execute(
                    "INSERT INTO users(id, username, display_name, enabled, created_at, password_hash, role) "
                    "VALUES (?, ?, ?, 1, ?, ?, ?)",
                    (identifier, args.username, args.display_name, now, password_hash, args.role),
                )
                enroll_reader(connection, identifier)
            elif args.command == "create-project":
                identifier = str(uuid4())
                connection.execute(
                    "INSERT INTO projects(id, project_number, name, archived, created_at) VALUES (?, ?, ?, 0, ?)",
                    (identifier, args.project_number, args.name, now),
                )
                if args.owner_id:
                    connection.execute(
                        "INSERT INTO project_memberships(project_id, user_id, role, granted_at) "
                        "VALUES (?, ?, 'owner', ?)",
                        (identifier, args.owner_id, now),
                    )
            elif args.command == "set-password":
                row = connection.execute(
                    "SELECT id FROM users WHERE username = ? COLLATE NOCASE", (args.username,)
                ).fetchone()
                if row is None:
                    raise ValueError("user not found")
                identifier = row["id"]
                connection.execute(
                    "UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, identifier)
                )
                connection.execute(
                    "UPDATE auth_sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                    (now, identifier),
                )
            elif args.command == "set-role":
                cursor = connection.execute(
                    "UPDATE users SET role = ? WHERE username = ? COLLATE NOCASE",
                    (args.role, args.username),
                )
                if cursor.rowcount == 0:
                    raise ValueError("user not found")
                identifier = args.username
            else:
                connection.execute(
                    "INSERT INTO project_memberships(project_id, user_id, role, granted_at) "
                    "VALUES (?, ?, ?, ?) ON CONFLICT(project_id, user_id) DO UPDATE "
                    "SET role = excluded.role, granted_at = excluded.granted_at",
                    (args.project_id, args.user_id, args.role, now),
                )
                identifier = args.user_id
    except sqlite3.IntegrityError as error:
        parser.error(f"record conflicts with existing data: {error}")
    except ValueError as error:
        parser.error(str(error))
    print(identifier)
