"""Local administration commands for bootstrapping the development database."""

import argparse
from getpass import getpass
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from forgepdm.application.auth import hash_password
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
    args = parser.parse_args()
    path = Path(os.environ.get("FORGEPDM_DATABASE", "var/forgepdm.sqlite3"))
    database = Database(path)
    database.initialize()
    if args.command == "create-user":
        args.username = args.username.strip()
        args.display_name = args.display_name.strip()
        if not args.username or not args.display_name:
            parser.error("username and display name must not be empty")
    elif args.command in {"set-password", "set-role"}:
        args.username = args.username.strip()
    if args.command in {"create-user", "set-password"}:
        password = getpass("Password (at least 12 characters): ")
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
