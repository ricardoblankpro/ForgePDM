"""Checkout leases, check-in, lifecycle transitions, and revision creation."""

import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from forgepdm.application.authorization import AuthorizationService
from forgepdm.domain.entities import (
    Checkout,
    Conflict,
    ItemRevision,
    LifecycleState,
    NotFound,
    User,
)
from forgepdm.infrastructure.database import Database


CHECKOUT_DURATION = timedelta(hours=8)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _checkout(row) -> Checkout:
    return Checkout(
        id=row["id"],
        revision_id=row["revision_id"],
        user_id=row["user_id"],
        acquired_at=datetime.fromisoformat(row["acquired_at"]),
        expires_at=datetime.fromisoformat(row["expires_at"]),
        released_at=datetime.fromisoformat(row["released_at"]) if row["released_at"] else None,
        version=row["version"],
    )


def _revision_label(sequence: int) -> str:
    label = ""
    value = sequence
    while value:
        value, remainder = divmod(value - 1, 26)
        label = chr(ord("A") + remainder) + label
    return label


class RevisionService:
    def __init__(self, database: Database, authorization: AuthorizationService):
        self.database = database
        self.authorization = authorization

    def acquire_checkout(self, user: User, revision_id: str) -> Checkout:
        now = _now()
        expires = now + CHECKOUT_DURATION
        with self.database.transaction() as connection:
            self.authorization.require_edit_revision(user, revision_id, connection)
            active = connection.execute(
                "SELECT * FROM checkouts WHERE revision_id = ? AND released_at IS NULL",
                (revision_id,),
            ).fetchone()
            if active is not None and datetime.fromisoformat(active["expires_at"]) <= now:
                connection.execute(
                    "UPDATE checkouts SET released_at = ?, release_reason = 'expired' WHERE id = ?",
                    (now.isoformat(), active["id"]),
                )
                active = None
            if active is not None and active["user_id"] != user.id:
                raise Conflict("revision is checked out by another user")
            if active is not None:
                connection.execute(
                    "UPDATE checkouts SET expires_at = ?, version = version + 1 WHERE id = ?",
                    (expires.isoformat(), active["id"]),
                )
                checkout_id = active["id"]
                event = "checkout.renewed"
            else:
                checkout_id = str(uuid4())
                connection.execute(
                    "INSERT INTO checkouts(id, revision_id, user_id, acquired_at, expires_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (checkout_id, revision_id, user.id, now.isoformat(), expires.isoformat()),
                )
                event = "checkout.acquired"
            self._audit(connection, user.id, event, "ItemRevision", revision_id, now, {})
            row = connection.execute(
                "SELECT * FROM checkouts WHERE id = ?", (checkout_id,)
            ).fetchone()
            return _checkout(row)

    def renew_checkout(self, user: User, revision_id: str) -> Checkout:
        now = _now()
        with self.database.transaction() as connection:
            self.authorization.require_edit_revision(user, revision_id, connection)
            active = connection.execute(
                "SELECT * FROM checkouts WHERE revision_id = ? AND released_at IS NULL",
                (revision_id,),
            ).fetchone()
            if active is None or datetime.fromisoformat(active["expires_at"]) <= now:
                raise Conflict("no active checkout to renew; acquire the checkout again")
            if active["user_id"] != user.id:
                raise Conflict("only the checkout owner can renew it")
            expires = now + CHECKOUT_DURATION
            connection.execute(
                "UPDATE checkouts SET expires_at = ?, version = version + 1 WHERE id = ?",
                (expires.isoformat(), active["id"]),
            )
            self._audit(
                connection, user.id, "checkout.renewed", "ItemRevision", revision_id, now, {}
            )
            row = connection.execute(
                "SELECT * FROM checkouts WHERE id = ?", (active["id"],)
            ).fetchone()
            return _checkout(row)

    def release_checkout(self, user: User, revision_id: str, reason: str = "") -> Checkout:
        reason = reason.strip()
        now = _now()
        with self.database.transaction() as connection:
            self.authorization.require_manage_revision(user, revision_id, connection)
            active = connection.execute(
                "SELECT * FROM checkouts WHERE revision_id = ? AND released_at IS NULL",
                (revision_id,),
            ).fetchone()
            if active is None:
                raise Conflict("revision has no active checkout")
            if datetime.fromisoformat(active["expires_at"]) <= now:
                reason = "expired"
            elif active["user_id"] != user.id:
                if user.role != "admin":
                    raise Conflict("only the checkout owner or an administrator can release it")
                if not reason:
                    raise ValueError(
                        "an administrator must provide a reason to release another user's checkout"
                    )
            connection.execute(
                "UPDATE checkouts SET released_at = ?, release_reason = ?, version = version + 1 WHERE id = ?",
                (now.isoformat(), reason or "released", active["id"]),
            )
            self._audit(
                connection,
                user.id,
                "checkout.released",
                "ItemRevision",
                revision_id,
                now,
                {"owner_id": active["user_id"], "reason": reason or "released"},
            )
            row = connection.execute(
                "SELECT * FROM checkouts WHERE id = ?", (active["id"],)
            ).fetchone()
            return _checkout(row)

    def require_checkout_owner(self, user: User, revision_id: str, connection=None) -> Checkout:
        if connection is None:
            with self.database.connection() as opened:
                return self.require_checkout_owner(user, revision_id, opened)
        now = _now().isoformat()
        row = connection.execute(
            "SELECT * FROM checkouts WHERE revision_id = ? AND released_at IS NULL AND expires_at > ?",
            (revision_id, now),
        ).fetchone()
        if row is None or row["user_id"] != user.id:
            raise Conflict("an active checkout owned by this user is required")
        return _checkout(row)

    def require_checkout_token(self, user, revision_id, checkout_id, version, connection=None):
        checkout = self.require_checkout_owner(user, revision_id, connection)
        if checkout.id != checkout_id or checkout.version != version:
            raise Conflict("checkout changed; refresh and review the operation before retrying")
        return checkout

    def current_checkout(self, user: User, revision_id: str) -> Checkout | None:
        with self.database.connection() as connection:
            self.authorization.require_read_revision(user, revision_id, connection)
            row = connection.execute(
                "SELECT * FROM checkouts WHERE revision_id = ? AND released_at IS NULL AND expires_at > ?",
                (revision_id, _now().isoformat()),
            ).fetchone()
        return _checkout(row) if row is not None else None

    def check_in(self, user: User, revision_id: str, change_note: str = "", *, expected_checkout_id=None, expected_checkout_version=None) -> None:
        change_note = change_note.strip()
        if len(change_note) > 2000:
            raise ValueError("check-in note must contain at most 2000 characters")
        now = _now()
        with self.database.transaction() as connection:
            self.authorization.require_edit_revision(user, revision_id, connection)
            checkout = self.require_checkout_owner(user, revision_id, connection)
            if expected_checkout_id is not None:
                self.require_checkout_token(user, revision_id, expected_checkout_id, expected_checkout_version, connection)
            connection.execute(
                "UPDATE item_revisions SET change_note = CASE WHEN ? = '' THEN change_note ELSE ? END, "
                "modified_at = ? WHERE id = ?",
                (change_note, change_note, now.isoformat(), revision_id),
            )
            connection.execute(
                "UPDATE checkouts SET released_at = ?, release_reason = 'checked in', version = version + 1 "
                "WHERE id = ?",
                (now.isoformat(), checkout.id),
            )
            self._audit(
                connection,
                user.id,
                "revision.checked_in",
                "ItemRevision",
                revision_id,
                now,
                {"change_note": change_note},
            )

    def transition_lifecycle(self, user: User, revision_id: str, target: LifecycleState) -> None:
        now = _now()
        with self.database.transaction() as connection:
            self.authorization.require_manage_revision(user, revision_id, connection)
            row = connection.execute(
                "SELECT lifecycle_state FROM item_revisions WHERE id = ?", (revision_id,)
            ).fetchone()
            material = connection.execute(
                "SELECT i.number_series FROM items i JOIN item_revisions r ON r.item_id=i.id WHERE r.id=?",
                (revision_id,),
            ).fetchone()
            if target == LifecycleState.RELEASED and material[0] == "M":
                if not connection.execute(
                    "SELECT 1 FROM revision_descriptions WHERE revision_id=? AND trim(description)!=''", (revision_id,)
                ).fetchone():
                    raise Conflict("raw materials require a description before release")
            current = LifecycleState(row["lifecycle_state"])
            allowed = {
                LifecycleState.WORKING: LifecycleState.RELEASED,
                LifecycleState.RELEASED: LifecycleState.OBSOLETE,
            }
            if allowed.get(current) != target:
                raise Conflict(f"transition from {current.value} to {target.value} is not allowed")
            if current == LifecycleState.WORKING:
                if target == LifecycleState.RELEASED:
                    unready = connection.execute(
                        "SELECT COUNT(*) AS count FROM bom_lines b "
                        "JOIN item_revisions component ON component.id = b.component_revision_id "
                        "WHERE b.parent_revision_id = ? AND component.lifecycle_state != 'released'",
                        (revision_id,),
                    ).fetchone()["count"]
                    if unready:
                        raise Conflict("all BOM component revisions must be Released first")
                checkout = connection.execute(
                    "SELECT id, expires_at FROM checkouts WHERE revision_id = ? AND released_at IS NULL",
                    (revision_id,),
                ).fetchone()
                if checkout is not None and datetime.fromisoformat(checkout["expires_at"]) > now:
                    raise Conflict(
                        "check in and release the active checkout before releasing this revision"
                    )
                if checkout is not None:
                    connection.execute(
                        "UPDATE checkouts SET released_at = ?, release_reason = 'expired' WHERE id = ?",
                        (now.isoformat(), checkout["id"]),
                    )
            connection.execute(
                "UPDATE item_revisions SET lifecycle_state = ?, modified_at = ? WHERE id = ?",
                (target.value, now.isoformat(), revision_id),
            )
            self._audit(
                connection,
                user.id,
                "revision.lifecycle_changed",
                "ItemRevision",
                revision_id,
                now,
                {"from": current.value, "to": target.value},
            )

    def create_next_revision(
        self, user: User, item_id: str, change_note: str, *, operation_id=None, expected_source_revision_id=None
    ) -> tuple[ItemRevision, Checkout]:
        change_note = change_note.strip()
        if not change_note or len(change_note) > 2000:
            raise ValueError("revision change note must contain 1 to 2000 characters")
        if operation_id is not None:
            operation_id = str(UUID(operation_id))
            if expected_source_revision_id is None:
                raise ValueError("expected source revision is required")
            expected_source_revision_id = str(UUID(expected_source_revision_id))
        now = _now()
        expires = now + CHECKOUT_DURATION
        with self.database.transaction() as connection:
            if operation_id is not None:
                existing = connection.execute("SELECT * FROM revision_operations WHERE actor_id=? AND operation_id=?", (user.id, operation_id)).fetchone()
                if existing is not None:
                    self.authorization.require_read_revision(user, existing["source_revision_id"], connection)
                    if (existing["item_id"], existing["source_revision_id"], existing["change_note"]) != (item_id, expected_source_revision_id, change_note):
                        raise Conflict("revision operation key was already used for different intent")
                    result = self._creation_result(existing["result_json"])
                    self.authorization.require_read_revision(user, result[0].id, connection)
                    return result
            item = connection.execute(
                "SELECT current_revision_id FROM items WHERE id = ?", (item_id,)
            ).fetchone()
            if item is None:
                raise NotFound("item not found")
            previous_id = item["current_revision_id"]
            if expected_source_revision_id is not None and previous_id != expected_source_revision_id:
                raise Conflict("source revision changed; review the current revision before retrying")
            self.authorization.require_manage_revision(user, previous_id, connection)
            previous = connection.execute(
                "SELECT lifecycle_state FROM item_revisions WHERE id = ?", (previous_id,)
            ).fetchone()
            if previous["lifecycle_state"] != LifecycleState.RELEASED.value:
                raise Conflict("a new revision can only be created from a Released revision")
            active = connection.execute(
                "SELECT id, expires_at FROM checkouts WHERE revision_id = ? AND released_at IS NULL",
                (previous_id,),
            ).fetchone()
            if active is not None and datetime.fromisoformat(active["expires_at"]) > now:
                raise Conflict("the previous revision still has an active checkout")
            if active is not None:
                connection.execute(
                    "UPDATE checkouts SET released_at = ?, release_reason = 'expired' WHERE id = ?",
                    (now.isoformat(), active["id"]),
                )
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence FROM item_revisions WHERE item_id = ?",
                (item_id,),
            ).fetchone()["next_sequence"]
            revision_id = str(uuid4())
            connection.execute(
                "INSERT INTO item_revisions(id, item_id, label, sequence, lifecycle_state, change_note, created_by, created_at, modified_at) "
                "VALUES (?, ?, ?, ?, 'working', ?, ?, ?, ?)",
                (
                    revision_id,
                    item_id,
                    _revision_label(sequence),
                    sequence,
                    change_note,
                    user.id,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            connection.execute(
                "UPDATE items SET current_revision_id = ? WHERE id = ?", (revision_id, item_id)
            )
            previous_bom = connection.execute(
                "SELECT component_revision_id, quantity, position FROM bom_lines "
                "WHERE parent_revision_id = ? ORDER BY position",
                (previous_id,),
            ).fetchall()
            for line in previous_bom:
                self.authorization.require_read_revision(
                    user, line["component_revision_id"], connection
                )
                connection.execute(
                    "INSERT INTO bom_lines(id, parent_revision_id, component_revision_id, quantity, position, created_by, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(uuid4()),
                        revision_id,
                        line["component_revision_id"],
                        line["quantity"],
                        line["position"],
                        user.id,
                        now.isoformat(),
                    ),
                )
            connection.execute("INSERT INTO revision_reference_mass SELECT ?,payload_json FROM revision_reference_mass WHERE revision_id=?", (revision_id,previous_id))
            connection.execute("INSERT INTO material_physical_links SELECT ?,snapshot_json FROM material_physical_links WHERE revision_id=?",(revision_id,previous_id))
            connection.execute("INSERT INTO part_physical_assignments SELECT ?,snapshot_json FROM part_physical_assignments WHERE revision_id=?",(revision_id,previous_id))
            connection.execute("INSERT INTO revision_descriptions SELECT ?,description,material_revision_id FROM revision_descriptions WHERE revision_id=?",(revision_id,previous_id))
            connection.execute(
                "INSERT INTO revision_material_data SELECT ?,specification_json FROM revision_material_data WHERE revision_id=?",
                (revision_id, previous_id),
            )
            material_bom = connection.execute(
                "SELECT payload_json FROM material_boms WHERE revision_id=?", (previous_id,)
            ).fetchone()
            if material_bom:
                copied = json.loads(material_bom[0])
                copied["readiness"] = "unreviewed"
                connection.execute(
                    "INSERT INTO material_boms VALUES (?,?,?,?)",
                    (revision_id, json.dumps(copied), user.id, now.isoformat()),
                )
            for line in connection.execute(
                "SELECT component_revision_id FROM material_bom_lines WHERE parent_revision_id=?",
                (previous_id,),
            ).fetchall():
                self.authorization.require_read_revision(user, line[0], connection)
            connection.execute(
                "INSERT INTO material_bom_lines SELECT ?,component_revision_id,position,quantity,uom,allowance_percent,note FROM material_bom_lines WHERE parent_revision_id=?",
                (revision_id, previous_id),
            )
            checkout_id = str(uuid4())
            connection.execute(
                "INSERT INTO checkouts(id, revision_id, user_id, acquired_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (checkout_id, revision_id, user.id, now.isoformat(), expires.isoformat()),
            )
            self._audit(
                connection,
                user.id,
                "revision.created",
                "ItemRevision",
                revision_id,
                now,
                {"item_id": item_id, "previous_revision_id": previous_id, "sequence": sequence},
            )
            self._audit(
                connection,
                user.id,
                "checkout.acquired",
                "ItemRevision",
                revision_id,
                now,
                {},
            )
            revision = ItemRevision(
                id=revision_id,
                item_id=item_id,
                label=_revision_label(sequence),
                sequence=sequence,
                lifecycle_state=LifecycleState.WORKING,
                change_note=change_note,
                created_by=user.id,
                created_at=now,
            )
            checkout_row = connection.execute(
                "SELECT * FROM checkouts WHERE id = ?", (checkout_id,)
            ).fetchone()
            checkout = _checkout(checkout_row)
            if operation_id is not None:
                result = json.dumps({"revision": asdict(revision), "checkout": asdict(checkout)}, default=lambda value: value.isoformat())
                connection.execute("INSERT INTO revision_operations VALUES (?,?,?,?,?,?)", (user.id, operation_id, item_id, expected_source_revision_id, change_note, result))
            return revision, checkout

    @staticmethod
    def _creation_result(payload):
        data = json.loads(payload)
        revision = data["revision"]
        revision["created_at"] = datetime.fromisoformat(revision["created_at"])
        revision["lifecycle_state"] = LifecycleState(revision["lifecycle_state"])
        return ItemRevision(**revision), _checkout(data["checkout"])

    def revision_operation(self, user, item_id, operation_id):
        with self.database.connection() as connection:
            row = connection.execute("SELECT * FROM revision_operations WHERE actor_id=? AND operation_id=? AND item_id=?", (user.id, str(UUID(operation_id)), item_id)).fetchone()
            if row is None:
                raise NotFound("revision operation not found")
            revision, checkout = self._creation_result(row["result_json"])
            self.authorization.require_read_revision(user, revision.id, connection)
            self.authorization.require_read_revision(user, row["source_revision_id"], connection)
            return revision, checkout

    @staticmethod
    def _audit(connection, actor_id, event_type, entity_type, entity_id, occurred_at, details):
        connection.execute(
            "INSERT INTO audit_events(id, actor_id, event_type, entity_type, entity_id, occurred_at, details_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid4()),
                actor_id,
                event_type,
                entity_type,
                entity_id,
                occurred_at.isoformat(),
                json.dumps(details),
            ),
        )
