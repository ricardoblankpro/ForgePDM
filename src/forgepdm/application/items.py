"""Item creation and retrieval use cases."""

import json
from datetime import datetime, timezone
from uuid import uuid4

from forgepdm.application.revisions import CHECKOUT_DURATION
from forgepdm.domain.entities import Item, ItemKind, ItemRevision, LifecycleState, NotFound
from forgepdm.infrastructure.database import Database


class ItemService:
    def __init__(self, database: Database):
        self.database = database

    def create_item(
        self,
        *,
        kind: ItemKind,
        name: str,
        description: str,
        created_by: str,
        project_id: str | None = None,
        change_note: str = "Initial revision",
    ) -> Item:
        name = name.strip()
        if not name:
            raise ValueError("name must not be empty")
        now = datetime.now(timezone.utc).isoformat()
        checkout_id = str(uuid4())
        checkout_expires_at = (datetime.fromisoformat(now) + CHECKOUT_DURATION).isoformat()
        item_id, revision_id = str(uuid4()), str(uuid4())
        with self.database.transaction() as connection:
            user = connection.execute(
                "SELECT id FROM users WHERE id = ? AND enabled = 1", (created_by,)
            ).fetchone()
            if user is None:
                raise NotFound("enabled user not found")
            if project_id is not None:
                project = connection.execute(
                    "SELECT id FROM projects WHERE id = ? AND archived = 0", (project_id,)
                ).fetchone()
                if project is None:
                    raise NotFound("active project not found")

            connection.execute(
                "INSERT OR IGNORE INTO number_counters(item_kind, next_value) VALUES (?, 1)",
                (kind.value,),
            )
            counter = connection.execute(
                "SELECT next_value FROM number_counters WHERE item_kind = ?", (kind.value,)
            ).fetchone()
            value = counter["next_value"]
            number = f"{kind.number_prefix}{value:06d}"
            connection.execute(
                "UPDATE number_counters SET next_value = ? WHERE item_kind = ?",
                (value + 1, kind.value),
            )
            connection.execute(
                "INSERT INTO items(id, number, kind, name, description, created_by, created_at, current_revision_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (item_id, number, kind.value, name, description.strip(), created_by, now, revision_id),
            )
            connection.execute(
                "INSERT INTO item_revisions(id, item_id, label, sequence, lifecycle_state, change_note, created_by, created_at, modified_at) "
                "VALUES (?, ?, 'A', 1, 'working', ?, ?, ?, ?)",
                (revision_id, item_id, change_note.strip(), created_by, now, now),
            )
            connection.execute(
                "INSERT INTO checkouts(id, revision_id, user_id, acquired_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (checkout_id, revision_id, created_by, now, checkout_expires_at),
            )
            connection.execute(
                "INSERT INTO audit_events(id, actor_id, event_type, entity_type, entity_id, occurred_at, details_json) "
                "VALUES (?, ?, 'item.created', 'Item', ?, ?, ?)",
                (str(uuid4()), created_by, item_id, now, json.dumps({"number": number, "kind": kind.value})),
            )
            connection.execute(
                "INSERT INTO audit_events(id, actor_id, event_type, entity_type, entity_id, occurred_at) "
                "VALUES (?, ?, 'checkout.acquired', 'ItemRevision', ?, ?)",
                (str(uuid4()), created_by, revision_id, now),
            )
            if project_id is not None:
                connection.execute(
                    "INSERT INTO project_items(project_id, item_id, added_at) VALUES (?, ?, ?)",
                    (project_id, item_id, now),
                )
        return Item(
            id=item_id,
            number=number,
            kind=kind,
            name=name,
            description=description.strip(),
            created_by=created_by,
            created_at=datetime.fromisoformat(now),
            current_revision_id=revision_id,
        )

    def get_item(self, item_id: str) -> tuple[Item, ItemRevision]:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT i.*, r.label, r.sequence, r.lifecycle_state, r.change_note, "
                "r.created_by AS revision_created_by, r.created_at AS revision_created_at "
                "FROM items i JOIN item_revisions r ON r.id = i.current_revision_id WHERE i.id = ?",
                (item_id,),
            ).fetchone()
        if row is None:
            raise NotFound("item not found")
        item = Item(
            id=row["id"], number=row["number"], kind=ItemKind(row["kind"]), name=row["name"],
            description=row["description"], created_by=row["created_by"],
            created_at=datetime.fromisoformat(row["created_at"]), current_revision_id=row["current_revision_id"],
        )
        revision = ItemRevision(
            id=row["current_revision_id"], item_id=row["id"], label=row["label"],
            sequence=row["sequence"], lifecycle_state=LifecycleState(row["lifecycle_state"]),
            change_note=row["change_note"], created_by=row["revision_created_by"],
            created_at=datetime.fromisoformat(row["revision_created_at"]),
        )
        return item, revision

