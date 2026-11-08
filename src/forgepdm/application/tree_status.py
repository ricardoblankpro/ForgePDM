"""Authorized, read-only revision summaries for CAD presentation."""

from datetime import UTC, datetime

from forgepdm.application.descriptions import DescriptionService
from forgepdm.domain.entities import Forbidden, NotFound


class TreeStatusService:
    def __init__(self, database, authorization):
        self.database = database
        self.authorization = authorization

    def revisions(self, user, revision_ids):
        if not 1 <= len(revision_ids) <= 200:
            raise ValueError("request between 1 and 200 revision IDs")
        now = datetime.now(UTC)
        result = []
        with self.database.connection() as connection:
            connection.execute("BEGIN")
            for revision_id in dict.fromkeys(revision_ids):
                try:
                    self.authorization.require_read_revision(user, revision_id, connection)
                except (Forbidden, NotFound):
                    result.append({"revision_id": revision_id, "available": False})
                    continue
                revision = connection.execute(
                    "SELECT r.item_id,r.label,r.sequence,r.lifecycle_state,i.number "
                    "FROM item_revisions r JOIN items i ON i.id=r.item_id WHERE r.id=?",
                    (revision_id,),
                ).fetchone()
                lease = connection.execute(
                    "SELECT c.user_id,u.display_name,u.username,c.expires_at FROM checkouts c "
                    "JOIN users u ON u.id=c.user_id WHERE c.revision_id=? AND c.released_at IS NULL",
                    (revision_id,),
                ).fetchone()
                checkout = None
                if lease and datetime.fromisoformat(lease["expires_at"]) > now:
                    checkout = dict(lease)
                    checkout["is_mine"] = lease["user_id"] == user.id
                newer = connection.execute(
                    "SELECT id,label FROM item_revisions WHERE item_id=? AND sequence>? "
                    "AND lifecycle_state!='obsolete' ORDER BY sequence DESC LIMIT 1",
                    (revision["item_id"], revision["sequence"]),
                ).fetchone()
                snapshot = connection.execute(
                    "SELECT d.id AS dataset_id,f.id AS file_id,f.content_hash,d.created_at "
                    "FROM datasets d JOIN dataset_files df ON df.dataset_id=d.id "
                    "JOIN files f ON f.id=df.file_id WHERE d.revision_id=? "
                    "AND d.dataset_type='native_cad' ORDER BY d.created_at DESC,d.id DESC,f.id DESC LIMIT 1",
                    (revision_id,),
                ).fetchone()
                result.append(
                    {
                        "revision_id": revision_id,
                        "available": True,
                        "description": DescriptionService.read_in(connection, revision_id)["description"],
                        "description_token": DescriptionService.read_in(connection, revision_id)["token"],
                        "item_id": revision["item_id"],
                        "item_number": revision["number"],
                        "revision_label": revision["label"],
                        "lifecycle_state": revision["lifecycle_state"],
                        "checkout": checkout,
                        "newer_revision": dict(newer) if newer else None,
                        "latest_snapshot": dict(snapshot) if snapshot else None,
                    }
                )
        return {"checked_at": now.isoformat(), "items": result}
