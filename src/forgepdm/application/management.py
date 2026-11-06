"""Account and project administration, scoped operational read models."""

import json
import re
from datetime import UTC, date, datetime
from uuid import uuid4

from forgepdm.application.auth import hash_password, verify_password
from forgepdm.application.catalog import CatalogService
from forgepdm.application.standard_library import enroll_reader
from forgepdm.domain.entities import Conflict, Forbidden, NotFound

ACTIVITY_SCOPE = "((e.entity_type='User' AND e.entity_id=?) OR (e.entity_type='Project' AND EXISTS (SELECT 1 FROM project_memberships pm WHERE pm.project_id=e.entity_id AND pm.user_id=?)) OR EXISTS (SELECT 1 FROM project_items pi JOIN project_memberships pm ON pm.project_id=pi.project_id WHERE pi.item_id=COALESCE(i.id,r.item_id) AND pm.user_id=?))"
ACTIVITY_JOINS = "FROM audit_events e JOIN users u ON u.id=e.actor_id LEFT JOIN datasets d ON e.entity_type='Dataset' AND d.id=e.entity_id LEFT JOIN item_revisions r ON (e.entity_type='ItemRevision' AND r.id=e.entity_id) OR (d.id IS NOT NULL AND r.id=d.revision_id) LEFT JOIN items i ON (e.entity_type='Item' AND i.id=e.entity_id) OR (r.id IS NOT NULL AND i.id=r.item_id) LEFT JOIN projects p ON e.entity_type='Project' AND p.id=e.entity_id LEFT JOIN users u2 ON e.entity_type='User' AND u2.id=e.entity_id"

USER_COLUMNS = "id,username,display_name,enabled,role,must_change_password,created_at"


def now():
    return datetime.now(UTC).isoformat()


def public_user(row):
    result = dict(row)
    for field in ("enabled", "must_change_password"):
        result[field] = bool(result[field])
    return result


class ManagementService:
    def __init__(self, database):
        self.database = database

    @staticmethod
    def admin(connection, user):
        row = connection.execute(
            "SELECT enabled,role,must_change_password FROM users WHERE id=?", (user.id,)
        ).fetchone()
        if (
            row is None
            or not row["enabled"]
            or row["role"] != "admin"
            or row["must_change_password"]
        ):
            raise Forbidden("administrator access is required")

    @staticmethod
    def audit(connection, actor, action, entity, identifier, details=None):
        connection.execute(
            "INSERT INTO audit_events(id,actor_id,event_type,entity_type,entity_id,occurred_at,details_json) VALUES (?,?,?,?,?,?,?)",
            (str(uuid4()), actor.id, action, entity, identifier, now(), json.dumps(details or {})),
        )

    @staticmethod
    def revoke(connection, user_id):
        connection.execute(
            "UPDATE auth_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
            (now(), user_id),
        )

    def users(self, actor, query="", limit=50, offset=0):
        CatalogService._bounds(limit, offset)
        with self.database.connection() as connection:
            self.admin(connection, actor)
            rows = connection.execute(
                f"SELECT {USER_COLUMNS} FROM users WHERE instr(lower(username||' '||display_name),lower(?))>0 ORDER BY username,id LIMIT ? OFFSET ?",
                (query.strip(), limit + 1, offset),
            ).fetchall()
        return {
            "items": [public_user(row) for row in rows[:limit]],
            "has_more": len(rows) > limit,
            "limit": limit,
            "offset": offset,
        }

    def create_user(self, actor, username, display_name, password, role="user"):
        username, display_name = username.strip(), display_name.strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@+-]{0,199}", username) or not display_name:
            raise ValueError("provide a valid username and display name")
        if role not in ("admin", "user"):
            raise ValueError("invalid user role")
        encoded = hash_password(password)
        with self.database.transaction() as connection:
            self.admin(connection, actor)
            if connection.execute(
                "SELECT 1 FROM users WHERE username=? COLLATE NOCASE", (username,)
            ).fetchone():
                raise Conflict("username already exists")
            identifier = str(uuid4())
            connection.execute(
                "INSERT INTO users(id,username,display_name,enabled,role,password_hash,must_change_password,created_at) VALUES (?,?,?,1,?,?,1,?)",
                (identifier, username, display_name, role, encoded, now()),
            )
            enroll_reader(connection, identifier)
            self.audit(
                connection,
                actor,
                "user.created",
                "User",
                identifier,
                {"username": username, "role": role},
            )
            return public_user(
                connection.execute(
                    f"SELECT {USER_COLUMNS} FROM users WHERE id=?", (identifier,)
                ).fetchone()
            )

    def update_user(self, actor, identifier, display_name, enabled, role):
        if not display_name.strip() or role not in ("admin", "user"):
            raise ValueError("provide a display name and valid role")
        with self.database.transaction() as connection:
            self.admin(connection, actor)
            old = connection.execute("SELECT * FROM users WHERE id=?", (identifier,)).fetchone()
            if old is None:
                raise NotFound("user not found")
            if old["enabled"] and old["role"] == "admin" and (not enabled or role != "admin"):
                total = connection.execute(
                    "SELECT COUNT(*) FROM users WHERE enabled=1 AND role='admin'"
                ).fetchone()[0]
                if total <= 1:
                    raise Conflict("the last active administrator cannot be disabled or demoted")
            if identifier == actor.id and (not enabled or role != "admin"):
                raise Conflict("use another administrator to disable or demote your own account")
            connection.execute(
                "UPDATE users SET display_name=?,enabled=?,role=? WHERE id=?",
                (display_name.strip(), int(enabled), role, identifier),
            )
            if not enabled or old["role"] != role:
                self.revoke(connection, identifier)
            self.audit(
                connection,
                actor,
                "user.updated",
                "User",
                identifier,
                {"enabled": enabled, "role": role},
            )
            if enabled and not old["enabled"]:
                enroll_reader(connection, identifier)
            return public_user(
                connection.execute(
                    f"SELECT {USER_COLUMNS} FROM users WHERE id=?", (identifier,)
                ).fetchone()
            )

    def reset_password(self, actor, identifier, password):
        encoded = hash_password(password)
        with self.database.transaction() as connection:
            self.admin(connection, actor)
            if identifier == actor.id:
                raise Conflict("use Change password for your own account")
            if (
                connection.execute("SELECT 1 FROM users WHERE id=?", (identifier,)).fetchone()
                is None
            ):
                raise NotFound("user not found")
            connection.execute(
                "UPDATE users SET password_hash=?,must_change_password=1 WHERE id=?",
                (encoded, identifier),
            )
            self.revoke(connection, identifier)
            self.audit(connection, actor, "user.password_reset", "User", identifier)
        return {"status": "password_reset"}

    def change_password(self, actor, current_password, new_password):
        with self.database.connection() as connection:
            old = connection.execute(
                "SELECT password_hash FROM users WHERE id=? AND enabled=1", (actor.id,)
            ).fetchone()
        if old is None or not verify_password(current_password, old["password_hash"]):
            raise Forbidden("current password is incorrect")
        if verify_password(new_password, old["password_hash"]):
            raise ValueError("choose a different password")
        encoded = hash_password(new_password)
        with self.database.transaction() as connection:
            updated = connection.execute(
                "UPDATE users SET password_hash=?,must_change_password=0 WHERE id=? AND enabled=1 AND password_hash=?",
                (encoded, actor.id, old["password_hash"]),
            )
            if not updated.rowcount:
                raise Conflict("account changed; sign in again before retrying")
            self.revoke(connection, actor.id)
            self.audit(connection, actor, "user.password_changed", "User", actor.id)
        return {"status": "password_changed", "sign_in_required": True}

    @staticmethod
    def project_access(connection, actor, identifier):
        row = connection.execute(
            "SELECT p.* FROM projects p WHERE p.id=? AND (?='admin' OR EXISTS (SELECT 1 FROM project_memberships pm WHERE pm.project_id=p.id AND pm.user_id=?))",
            (identifier, actor.role, actor.id),
        ).fetchone()
        if row is None:
            raise NotFound("project not found")
        return dict(row)

    def projects(self, actor, archived=False, limit=50, offset=0):
        CatalogService._bounds(limit, offset)
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT p.* FROM projects p WHERE (?=1 OR p.archived=0) AND (?='admin' OR EXISTS (SELECT 1 FROM project_memberships pm WHERE pm.project_id=p.id AND pm.user_id=?)) ORDER BY p.project_number,p.id LIMIT ? OFFSET ?",
                (int(archived), actor.role, actor.id, limit + 1, offset),
            ).fetchall()
        return CatalogService._page(rows, limit, offset)

    def save_project(self, actor, values, identifier=None):
        values = dict(values)
        for key in ("project_number", "name", "customer", "description"):
            values[key] = values[key].strip()
        if not values["project_number"] or not values["name"]:
            raise ValueError("project number and name are required")
        if values["due_date"]:
            values["due_date"] = date.fromisoformat(str(values["due_date"])).isoformat()
        with self.database.transaction() as connection:
            self.admin(connection, actor)
            if identifier:
                existing = self.project_access(connection, actor, identifier)
                if existing.get("is_standard_library") and values["archived"]:
                    raise Conflict("Standard Parts Library cannot be archived")
            if connection.execute(
                "SELECT 1 FROM projects WHERE project_number=? AND id!=?",
                (values["project_number"], identifier or ""),
            ).fetchone():
                raise Conflict("project number already exists")
            action = "project.updated" if identifier else "project.created"
            identifier = identifier or str(uuid4())
            columns = ("project_number", "name", "customer", "due_date", "description", "archived")
            if action == "project.created":
                connection.execute(
                    "INSERT INTO projects(project_number,name,customer,due_date,description,archived,id,created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (*(values[key] for key in columns), identifier, now()),
                )
            else:
                connection.execute(
                    "UPDATE projects SET project_number=?,name=?,customer=?,due_date=?,description=?,archived=? WHERE id=?",
                    (*(values[key] for key in columns), identifier),
                )
            self.audit(
                connection, actor, action, "Project", identifier, {"archived": values["archived"]}
            )
            return self.project_access(connection, actor, identifier)

    def members(self, actor, identifier):
        with self.database.connection() as connection:
            self.admin(connection, actor)
            self.project_access(connection, actor, identifier)
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT u.id,u.username,u.display_name,u.enabled,pm.role FROM project_memberships pm JOIN users u ON u.id=pm.user_id WHERE pm.project_id=? ORDER BY u.username",
                    (identifier,),
                )
            ]

    def membership(self, actor, project_id, user_id, role=None):
        if role is not None and role not in ("owner", "editor", "viewer"):
            raise ValueError("invalid project role")
        with self.database.transaction() as connection:
            self.admin(connection, actor)
            self.project_access(connection, actor, project_id)
            if connection.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone() is None:
                raise NotFound("user not found")
            if role is None:
                connection.execute(
                    "DELETE FROM project_memberships WHERE project_id=? AND user_id=?",
                    (project_id, user_id),
                )
            else:
                connection.execute(
                    "INSERT INTO project_memberships(project_id,user_id,role,granted_at) VALUES (?,?,?,?) ON CONFLICT(project_id,user_id) DO UPDATE SET role=excluded.role,granted_at=excluded.granted_at",
                    (project_id, user_id, role, now()),
                )
            self.audit(
                connection,
                actor,
                "project.member_removed" if role is None else "project.member_set",
                "Project",
                project_id,
                {"user_id": user_id, "role": role},
            )
        return {"status": "updated"}

    def checkouts(self, actor, limit=50, offset=0):
        CatalogService._bounds(limit, offset)
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT c.id,c.acquired_at,c.expires_at,c.version,c.revision_id,r.label AS revision_label,i.id AS item_id,i.number AS item_number,i.name AS item_name,CASE WHEN c.expires_at>? THEN 'active' ELSE 'expired' END AS status FROM checkouts c JOIN item_revisions r ON r.id=c.revision_id JOIN items i ON i.id=r.item_id WHERE c.user_id=? AND c.released_at IS NULL AND (?='admin' OR EXISTS (SELECT 1 FROM project_items pi JOIN project_memberships pm ON pm.project_id=pi.project_id WHERE pi.item_id=i.id AND pm.user_id=?)) ORDER BY c.expires_at,c.id LIMIT ? OFFSET ?",
                (now(), actor.id, actor.role, actor.id, limit + 1, offset),
            ).fetchall()
        return CatalogService._page(rows, limit, offset)

    def activity(
        self,
        actor,
        *,
        project_id=None,
        actor_id=None,
        action="",
        query="",
        start=None,
        end=None,
        limit=50,
        offset=0,
    ):
        CatalogService._bounds(limit, offset)
        clauses, params = [], []
        with self.database.connection() as connection:
            connection.execute("BEGIN")
            if project_id:
                self.project_access(connection, actor, project_id)
                clauses.append(
                    "(e.entity_type='Project' AND e.entity_id=? OR EXISTS (SELECT 1 FROM project_items scope WHERE scope.item_id=COALESCE(i.id,r.item_id) AND scope.project_id=?))"
                )
                params.extend([project_id, project_id])
            if actor.role != "admin":
                clauses.append(ACTIVITY_SCOPE)
                params.extend([actor.id, actor.id, actor.id])
            if actor_id:
                clauses.append("e.actor_id=?")
                params.append(actor_id)
            if action:
                clauses.append("e.event_type=?")
                params.append(action)
            if query:
                clauses.append(
                    "instr(lower(e.event_type||' '||COALESCE(i.number,'')||' '||COALESCE(i.name,'')||' '||u.username),lower(?))>0"
                )
                params.append(query.strip())
            if start:
                clauses.append("substr(e.occurred_at,1,10)>=?")
                params.append(start)
            if end:
                clauses.append("substr(e.occurred_at,1,10)<=?")
                params.append(end)
            if start and end and start > end:
                raise ValueError("start date must be before end date")
            rows = connection.execute(
                "SELECT e.id,e.actor_id,u.username,e.event_type,e.entity_type,e.entity_id,e.occurred_at,e.details_json,i.id AS item_id,i.number AS item_number,r.id AS revision_id,COALESCE(i.number,p.project_number,u2.username,e.entity_type) AS subject "
                + ACTIVITY_JOINS
                + (" WHERE " + " AND ".join(clauses) if clauses else "")
                + " ORDER BY e.occurred_at DESC,e.id DESC LIMIT ? OFFSET ?",
                (*params, limit + 1, offset),
            ).fetchall()
        result = CatalogService._page(rows, limit, offset)
        for row in result["items"]:
            details = row.pop("details_json")
            if actor.role == "admin":
                row["details"] = json.loads(details)
        return result

    def activity_actors(self, actor, limit=50, offset=0):
        CatalogService._bounds(limit, offset)
        scope = " WHERE " + ACTIVITY_SCOPE if actor.role != "admin" else ""
        params = [actor.id, actor.id, actor.id] if actor.role != "admin" else []
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT DISTINCT u.id,u.username "
                + ACTIVITY_JOINS
                + scope
                + " ORDER BY u.username,u.id LIMIT ? OFFSET ?",
                (*params, limit + 1, offset),
            ).fetchall()
        return CatalogService._page(rows, limit, offset)
