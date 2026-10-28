"""Project-level authorization policies."""

from forgepdm.domain.entities import Conflict, Forbidden, NotFound, User
from forgepdm.infrastructure.database import Database


class AuthorizationService:
    def __init__(self, database: Database):
        self.database = database

    def require_create_item(self, user: User, project_id: str | None) -> None:
        if user.role == "admin":
            return
        if project_id is None:
            raise Forbidden("only administrators may create projectless items")
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT role FROM project_memberships WHERE user_id = ? AND project_id = ?",
                (user.id, project_id),
            ).fetchone()
        if row is None or row["role"] not in {"owner", "editor"}:
            raise Forbidden("project editor access is required")

    def require_read_item(self, user: User, item_id: str) -> None:
        if user.role == "admin":
            return
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM items i JOIN project_items pi ON pi.item_id = i.id "
                "JOIN project_memberships pm ON pm.project_id = pi.project_id "
                "WHERE i.id = ? AND pm.user_id = ? LIMIT 1",
                (item_id, user.id),
            ).fetchone()
        if row is None:
            # Avoid disclosing whether an inaccessible item exists.
            raise Forbidden("item is not available to this user")

    def require_read_revision(self, user: User, revision_id: str, connection=None) -> None:
        if connection is None:
            with self.database.connection() as opened:
                self._require_revision_access(user, revision_id, opened, write=False)
            return
        self._require_revision_access(user, revision_id, connection, write=False)

    def require_edit_revision(self, user: User, revision_id: str, connection=None) -> None:
        if connection is None:
            with self.database.connection() as opened:
                self._require_revision_access(user, revision_id, opened, write=True)
            return
        self._require_revision_access(user, revision_id, connection, write=True)

    def require_manage_revision(self, user: User, revision_id: str, connection) -> None:
        self._require_revision_access(
            user, revision_id, connection, write=True, require_working=False
        )

    @staticmethod
    def _require_revision_access(
        user: User,
        revision_id: str,
        connection,
        *,
        write: bool,
        require_working: bool = True,
    ) -> None:
        row = connection.execute(
            "SELECT r.lifecycle_state, "
            "EXISTS (SELECT 1 FROM project_items pi JOIN project_memberships pm "
            "ON pm.project_id = pi.project_id WHERE pi.item_id = r.item_id AND pm.user_id = ?) AS can_read, "
            "EXISTS (SELECT 1 FROM project_items pi JOIN project_memberships pm "
            "ON pm.project_id = pi.project_id WHERE pi.item_id = r.item_id AND pm.user_id = ? "
            "AND pm.role IN ('owner', 'editor')) AS can_edit "
            "FROM item_revisions r WHERE r.id = ?",
            (user.id, user.id, revision_id),
        ).fetchone()
        if row is None:
            raise NotFound("item revision not found")
        if user.role != "admin":
            allowed = row["can_edit"] if write else row["can_read"]
            if not allowed:
                raise Forbidden("item revision is not available to this user")
        if write and require_working and row["lifecycle_state"] != "working":
            raise Conflict("files can only be attached to a Working revision")
