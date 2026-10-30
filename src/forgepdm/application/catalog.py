"""Authorized catalog queries for thin clients; no CAD dependencies."""

from forgepdm.application.authorization import AuthorizationService
from forgepdm.domain.entities import NotFound, User
from forgepdm.infrastructure.database import Database


class CatalogService:
    def __init__(self, database: Database, authorization: AuthorizationService):
        self.database = database
        self.authorization = authorization

    @staticmethod
    def _bounds(limit, offset):
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("limit must be 1 to 100 and offset must be non-negative")

    @staticmethod
    def _page(rows, limit, offset):
        return {
            "items": [dict(row) for row in rows[:limit]],
            "limit": limit,
            "offset": offset,
            "has_more": len(rows) > limit,
        }

    def projects(self, user: User, *, editable=False, limit=50, offset=0):
        self._bounds(limit, offset)
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT p.id, p.project_number, p.name, "
                "CASE WHEN ? = 'admin' THEN 1 WHEN pm.role IN ('owner','editor') "
                "THEN 1 ELSE 0 END AS can_edit FROM projects p "
                "LEFT JOIN project_memberships pm ON pm.project_id=p.id AND pm.user_id=? "
                "WHERE p.archived=0 AND (?='admin' OR pm.user_id IS NOT NULL) "
                "AND (?=0 OR ?='admin' OR pm.role IN ('owner','editor')) "
                "ORDER BY p.project_number, p.id LIMIT ? OFFSET ?",
                (user.role, user.id, user.role, int(editable), user.role, limit + 1, offset),
            ).fetchall()
        result = self._page(rows, limit, offset)
        for project in result["items"]:
            project["can_edit"] = bool(project["can_edit"])
        return result

    def search_items(self, user: User, *, query="", limit=50, offset=0):
        self._bounds(limit, offset)
        query = query.strip()
        if len(query) > 200:
            raise ValueError("search text must contain at most 200 characters")
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT i.id, i.number, i.kind, i.name, i.description, i.current_revision_id, "
                "r.label AS revision_label, r.lifecycle_state FROM items i "
                "JOIN item_revisions r ON r.id=i.current_revision_id "
                "WHERE (?='admin' OR EXISTS (SELECT 1 FROM project_items pi "
                "JOIN project_memberships pm ON pm.project_id=pi.project_id "
                "WHERE pi.item_id=i.id AND pm.user_id=?)) "
                "AND (?='' OR instr(lower(i.number),lower(?))>0 "
                "OR instr(lower(i.name),lower(?))>0 OR instr(lower(i.description),lower(?))>0) "
                "ORDER BY i.number, i.id LIMIT ? OFFSET ?",
                (user.role, user.id, query, query, query, query, limit + 1, offset),
            ).fetchall()
        return self._page(rows, limit, offset)

    def revisions(self, user: User, item_id: str, *, limit=50, offset=0):
        self._bounds(limit, offset)
        with self.database.connection() as connection:
            connection.execute("BEGIN")
            item = connection.execute(
                "SELECT current_revision_id FROM items WHERE id=?", (item_id,)
            ).fetchone()
            if item is None:
                raise NotFound("item not found")
            self.authorization.require_read_revision(user, item["current_revision_id"], connection)
            rows = connection.execute(
                "SELECT id, item_id, label, sequence, lifecycle_state, change_note, created_at "
                "FROM item_revisions WHERE item_id=? ORDER BY sequence DESC LIMIT ? OFFSET ?",
                (item_id, limit + 1, offset),
            ).fetchall()
        return self._page(rows, limit, offset)

    def revision(self, user: User, revision_id: str):
        with self.database.connection() as connection:
            connection.execute("BEGIN")
            self.authorization.require_read_revision(user, revision_id, connection)
            row = connection.execute(
                "SELECT r.id, r.item_id, r.label, r.sequence, r.lifecycle_state, r.change_note, "
                "r.created_at, i.number AS item_number, i.name AS item_name, i.kind AS item_kind "
                "FROM item_revisions r JOIN items i ON i.id=r.item_id WHERE r.id=?",
                (revision_id,),
            ).fetchone()
        return dict(row)
