"""Revision-bound assembly structures and where-used queries."""

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from forgepdm.application.authorization import AuthorizationService
from forgepdm.application.revisions import RevisionService
from forgepdm.domain.entities import Conflict, Forbidden, NotFound, User
from forgepdm.infrastructure.database import Database


class BOMService:
    def __init__(
        self,
        database: Database,
        authorization: AuthorizationService,
        revisions: RevisionService,
    ):
        self.database = database
        self.authorization = authorization
        self.revisions = revisions

    def replace_bom(self, user: User, parent_revision_id: str, requested_lines: list[dict]) -> list[dict]:
        prepared: list[tuple[str, Decimal, int]] = []
        positions: set[int] = set()
        for requested in requested_lines:
            component_revision_id = str(requested["component_revision_id"])
            try:
                quantity = Decimal(str(requested["quantity"]))
            except (InvalidOperation, ValueError) as error:
                raise ValueError("BOM quantity must be a positive decimal") from error
            position = int(requested["position"])
            if not quantity.is_finite() or quantity <= 0:
                raise ValueError("BOM quantity must be a positive decimal")
            if position <= 0 or position in positions:
                raise ValueError("BOM positions must be unique positive integers")
            positions.add(position)
            prepared.append((component_revision_id, quantity, position))

        now = datetime.now(timezone.utc)
        with self.database.transaction() as connection:
            self.authorization.require_edit_revision(user, parent_revision_id, connection)
            self.revisions.require_checkout_owner(user, parent_revision_id, connection)
            parent = connection.execute(
                "SELECT r.item_id, i.kind FROM item_revisions r JOIN items i ON i.id = r.item_id "
                "WHERE r.id = ?",
                (parent_revision_id,),
            ).fetchone()
            if parent is None:
                raise NotFound("parent revision not found")
            if parent["kind"] != "assembly":
                raise Conflict("BOM lines can only be assigned to an assembly revision")

            for component_revision_id, _, _ in prepared:
                component = connection.execute(
                    "SELECT lifecycle_state FROM item_revisions WHERE id = ?",
                    (component_revision_id,),
                ).fetchone()
                if component is None:
                    raise NotFound("component revision not found")
                if component["lifecycle_state"] == "obsolete":
                    raise Conflict("obsolete revisions cannot be used as BOM components")
                self.authorization.require_read_revision(user, component_revision_id, connection)

            connection.execute("DELETE FROM bom_lines WHERE parent_revision_id = ?", (parent_revision_id,))
            new_ids = []
            for component_revision_id, quantity, position in prepared:
                cycle = connection.execute(
                    "WITH RECURSIVE descendants(revision_id) AS ("
                    "SELECT ? UNION "
                    "SELECT b.component_revision_id FROM bom_lines b "
                    "JOIN descendants d ON b.parent_revision_id = d.revision_id) "
                    "SELECT 1 FROM descendants d JOIN item_revisions r ON r.id = d.revision_id "
                    "WHERE r.item_id = ? LIMIT 1",
                    (component_revision_id, parent["item_id"]),
                ).fetchone()
                if cycle is not None:
                    raise Conflict("BOM would create an assembly cycle")
                line_id = str(uuid4())
                connection.execute(
                    "INSERT INTO bom_lines(id, parent_revision_id, component_revision_id, quantity, position, created_by, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        line_id,
                        parent_revision_id,
                        component_revision_id,
                        format(quantity.normalize(), "f"),
                        position,
                        user.id,
                        now.isoformat(),
                    ),
                )
                new_ids.append(line_id)
            connection.execute(
                "INSERT INTO audit_events(id, actor_id, event_type, entity_type, entity_id, occurred_at, details_json) "
                "VALUES (?, ?, 'bom.replaced', 'ItemRevision', ?, ?, ?)",
                (
                    str(uuid4()),
                    user.id,
                    parent_revision_id,
                    now.isoformat(),
                    json.dumps({"line_count": len(new_ids)}),
                ),
            )
        return self.get_bom(user, parent_revision_id)

    def get_bom(self, user: User, parent_revision_id: str, recursive: bool = False) -> list[dict]:
        with self.database.connection() as connection:
            self.authorization.require_read_revision(user, parent_revision_id, connection)
            return self._read_bom(connection, user, parent_revision_id, recursive, 1, set())

    def _read_bom(
        self,
        connection,
        user: User,
        parent_revision_id: str,
        recursive: bool,
        level: int,
        ancestry: set[str],
    ) -> list[dict]:
        if parent_revision_id in ancestry:
            raise Conflict("stored BOM contains a cycle")
        ancestry = ancestry | {parent_revision_id}
        rows = connection.execute(
            "SELECT b.id AS line_id, b.parent_revision_id, b.component_revision_id, b.quantity, b.position, "
            "i.id AS item_id, i.number AS item_number, i.kind AS item_kind, i.name AS item_name, "
            "r.label AS revision_label, r.lifecycle_state "
            "FROM bom_lines b JOIN item_revisions r ON r.id = b.component_revision_id "
            "JOIN items i ON i.id = r.item_id WHERE b.parent_revision_id = ? ORDER BY b.position",
            (parent_revision_id,),
        ).fetchall()
        result = []
        for row in rows:
            self.authorization.require_read_revision(user, row["component_revision_id"], connection)
            line = {
                "id": row["line_id"],
                "parent_revision_id": row["parent_revision_id"],
                "component_revision_id": row["component_revision_id"],
                "item_id": row["item_id"],
                "item_number": row["item_number"],
                "item_kind": row["item_kind"],
                "item_name": row["item_name"],
                "revision_label": row["revision_label"],
                "lifecycle_state": row["lifecycle_state"],
                "quantity": row["quantity"],
                "position": row["position"],
                "level": level,
            }
            result.append(line)
            if recursive and row["item_kind"] == "assembly":
                line["children"] = self._read_bom(
                    connection,
                    user,
                    row["component_revision_id"],
                    recursive,
                    level + 1,
                    ancestry,
                )
        return result

    def where_used(self, user: User, item_id: str) -> list[dict]:
        with self.database.connection() as connection:
            exists = connection.execute("SELECT 1 FROM items WHERE id = ?", (item_id,)).fetchone()
            if exists is None:
                raise NotFound("item not found")
            self.authorization.require_read_item(user, item_id)
            rows = connection.execute(
                "SELECT b.id AS line_id, b.parent_revision_id, b.component_revision_id, b.quantity, b.position, "
                "parent_item.id AS parent_item_id, parent_item.number AS parent_item_number, "
                "parent_item.name AS parent_item_name, parent_item_revision.label AS parent_revision_label "
                "FROM bom_lines b "
                "JOIN item_revisions component_revision ON component_revision.id = b.component_revision_id "
                "JOIN item_revisions parent_item_revision ON parent_item_revision.id = b.parent_revision_id "
                "JOIN items parent_item ON parent_item.id = parent_item_revision.item_id "
                "WHERE component_revision.item_id = ? ORDER BY parent_item.number, parent_item_revision.sequence, b.position",
                (item_id,),
            ).fetchall()
            result = []
            for row in rows:
                try:
                    self.authorization.require_read_revision(
                        user, row["parent_revision_id"], connection
                    )
                except Forbidden:
                    continue
                result.append(
                    {
                        "line_id": row["line_id"],
                        "parent_item_id": row["parent_item_id"],
                        "parent_item_number": row["parent_item_number"],
                        "parent_item_name": row["parent_item_name"],
                        "parent_revision_id": row["parent_revision_id"],
                        "parent_revision_label": row["parent_revision_label"],
                        "component_revision_id": row["component_revision_id"],
                        "quantity": row["quantity"],
                        "position": row["position"],
                    }
                )
            return result
