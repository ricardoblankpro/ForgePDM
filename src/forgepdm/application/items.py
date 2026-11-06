"""Item creation and retrieval use cases."""

import json
from datetime import datetime, timezone
from uuid import uuid4

from forgepdm.application.revisions import CHECKOUT_DURATION
from forgepdm.application.standard_library import creation_project
from forgepdm.domain.entities import (
    Conflict,
    Item,
    ItemKind,
    ItemRevision,
    LifecycleState,
    NotFound,
)
from forgepdm.domain.standard_parts import encode, specification
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
        number_series: str | None = None,
        standard_specification: dict | None = None,
    ) -> Item:
        series = number_series if number_series is not None else kind.number_prefix
        if (kind.value, series) not in {("part", "P"), ("part", "S"), ("assembly", "A")}:
            raise ValueError("invalid item kind and numbering series")
        spec = specification(standard_specification) if standard_specification is not None else None
        if spec is not None and series != "S":
            raise ValueError("Standard specifications require S numbering")
        name = name.strip()
        if not name:
            raise ValueError("name must not be empty")
        now = datetime.now(timezone.utc).isoformat()
        checkout_id = str(uuid4())
        checkout_expires_at = (datetime.fromisoformat(now) + CHECKOUT_DURATION).isoformat()
        item_id, revision_id = str(uuid4()), str(uuid4())
        with self.database.transaction() as connection:
            user = connection.execute(
                "SELECT id,role FROM users WHERE id = ? AND enabled = 1", (created_by,)
            ).fetchone()
            if user is None:
                raise NotFound("enabled user not found")
            project_id = creation_project(connection, created_by, user["role"], series, project_id)
            if project_id is not None:
                project = connection.execute(
                    "SELECT id FROM projects WHERE id = ? AND archived = 0", (project_id,)
                ).fetchone()
                if project is None:
                    raise NotFound("active project not found")

            scope = project_id or ("user:" + created_by)
            if spec is not None:
                existing = connection.execute(
                    "SELECT s.item_id FROM standard_specifications s JOIN project_items pi ON pi.item_id=s.item_id WHERE pi.project_id=? AND s.specification_json=?",
                    (project_id, encode(spec)),
                ).fetchone()
                if existing is not None:
                    raise Conflict(
                        "This specification already exists in the Standard Parts Library; refresh catalog matches"
                    )
            connection.execute(
                "INSERT OR IGNORE INTO series_counters(series, next_value) VALUES (?, 1)",
                (series,),
            )
            counter = connection.execute(
                "SELECT next_value FROM series_counters WHERE series = ?", (series,)
            ).fetchone()
            value = counter["next_value"]
            number = f"{series}{value:06d}"
            connection.execute(
                "UPDATE series_counters SET next_value = ? WHERE series = ?",
                (value + 1, series),
            )
            connection.execute(
                "INSERT INTO items(id, number, kind, name, description, created_by, created_at, current_revision_id, number_series) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item_id,
                    number,
                    kind.value,
                    name,
                    description.strip(),
                    created_by,
                    now,
                    revision_id,
                    series,
                ),
            )
            if spec is not None:
                connection.execute(
                    "INSERT INTO standard_specifications VALUES (?,?,?,?)",
                    (item_id, scope, encode(spec["geometry"]), encode(spec)),
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
                (
                    str(uuid4()),
                    created_by,
                    item_id,
                    now,
                    json.dumps({"number": number, "kind": kind.value}),
                ),
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
            id=row["id"],
            number=row["number"],
            kind=ItemKind(row["kind"]),
            name=row["name"],
            description=row["description"],
            created_by=row["created_by"],
            created_at=datetime.fromisoformat(row["created_at"]),
            current_revision_id=row["current_revision_id"],
        )
        revision = ItemRevision(
            id=row["current_revision_id"],
            item_id=row["id"],
            label=row["label"],
            sequence=row["sequence"],
            lifecycle_state=LifecycleState(row["lifecycle_state"]),
            change_note=row["change_note"],
            created_by=row["revision_created_by"],
            created_at=datetime.fromisoformat(row["revision_created_at"]),
        )
        return item, revision
