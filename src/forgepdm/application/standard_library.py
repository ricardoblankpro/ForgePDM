"""Shared S-item ownership using ordinary project permissions."""

from forgepdm.domain.entities import Conflict, Forbidden


def library(connection):
    row = connection.execute(
        "SELECT id,name,archived FROM projects WHERE is_standard_library=1"
    ).fetchone()
    if row is None or row["archived"]:
        raise Conflict(
            "Standard Parts Library is unavailable; update or restore the backend library configuration"
        )
    return row


def can_register(connection, user_id, role, project_id):
    if role == "admin":
        return True
    row = connection.execute(
        "SELECT role FROM project_memberships WHERE project_id=? AND user_id=?",
        (project_id, user_id),
    ).fetchone()
    return row is not None and row["role"] in ("owner", "editor")


def creation_project(connection, user_id, role, series, project_id):
    if series == "S":
        project_id = library(connection)["id"]
        if not can_register(connection, user_id, role, project_id):
            raise Forbidden(
                "Standard Parts Library maintainer access is required to register or edit standard parts"
            )
    elif project_id is not None:
        row = connection.execute(
            "SELECT is_standard_library FROM projects WHERE id=?", (project_id,)
        ).fetchone()
        if row is not None and row["is_standard_library"]:
            raise ValueError(
                "Standard Parts Library accepts S items only; choose an engineering project for P/A items"
            )
    return project_id


def enroll_reader(connection, user_id):
    """Default library access for enabled accounts, without promoting maintainers."""
    connection.execute(
        "INSERT OR IGNORE INTO project_memberships(project_id,user_id,role,granted_at) "
        "SELECT p.id,u.id,'viewer',strftime('%Y-%m-%dT%H:%M:%f+00:00','now') "
        "FROM projects p JOIN users u ON u.id=? WHERE p.is_standard_library=1 AND u.enabled=1",
        (user_id,),
    )
