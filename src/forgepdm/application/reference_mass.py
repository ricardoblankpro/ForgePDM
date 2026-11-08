"""Revision-bound supplier mass: explicit provenance, bounded lookup and CSV feed."""

import csv
import io
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from forgepdm.domain.entities import Conflict, Forbidden
from forgepdm.domain.reference_mass import mass_kg, source_url, specification_key
from forgepdm.domain.standard_parts import encode, specification

CSV_FIELDS = {
    "specification_json",
    "supplier",
    "source_article",
    "source_url",
    "mass",
    "unit",
    "quantity",
}


class ReferenceMassService:
    def __init__(self, database, authorization, revisions, provider=None):
        self.database, self.authorization, self.revisions = database, authorization, revisions
        self.provider = provider

    def _spec(self, c, user, revision_id):
        self.authorization.require_read_revision(user, revision_id, c)
        row = c.execute(
            "SELECT i.number_series,s.specification_json,r.lifecycle_state FROM item_revisions r "
            "JOIN items i ON i.id=r.item_id LEFT JOIN standard_specifications s ON s.item_id=i.id WHERE r.id=?",
            (revision_id,),
        ).fetchone()
        if row["number_series"] != "S":
            raise Conflict("Supplier reference mass belongs to S revisions")
        return json.loads(row["specification_json"]) if row["specification_json"] else None

    @staticmethod
    def _saved(c, revision_id, spec):
        row = c.execute(
            "SELECT payload_json FROM revision_reference_mass WHERE revision_id=?", (revision_id,)
        ).fetchone()
        if row:
            value = json.loads(row[0])
            if spec and value["specification_key"] == specification_key(spec):
                return value
        return None

    def read(self, user, revision_id):
        with self.database.connection() as c:
            spec = self._spec(c, user, revision_id)
            return self._saved(c, revision_id, spec) or {
                "mass_kg": None,
                "status": "unavailable",
                "reason": "No supplier reference mass saved",
            }

    def lookup(self, user, revision_id):
        # All network I/O happens outside DB transactions. Revalidate ownership,
        # lifecycle and specification before committing the result.
        now = datetime.now(UTC)
        with self.database.connection() as c:
            spec = self._spec(c, user, revision_id)
            saved = self._saved(c, revision_id, spec)
            if saved:
                return saved
            if not spec:
                return {
                    "mass_kg": None,
                    "status": "unavailable",
                    "reason": "No structured fastener specification",
                }
            try:
                self.authorization.require_edit_revision(user, revision_id, c)
                self.revisions.require_checkout_owner(user, revision_id, c)
            except (Conflict, Forbidden):
                return {
                    "mass_kg": None,
                    "status": "unavailable",
                    "reason": "An owned Working checkout is required to save reference mass",
                }
            key = specification_key(spec)
            feed = c.execute(
                "SELECT payload_json FROM supplier_mass_feed WHERE specification_key=?", (key,)
            ).fetchone()
        # Reserve attempts transactionally: concurrent association/registration
        # requests share a cooldown rather than making duplicate supplier reads.
        with self.database.transaction() as c:
            self.authorization.require_edit_revision(user, revision_id, c)
            self.revisions.require_checkout_owner(user, revision_id, c)
            previous = c.execute(
                "SELECT attempted_at FROM supplier_mass_attempts WHERE revision_id=?",
                (revision_id,),
            ).fetchone()
            if (
                not feed
                and previous
                and datetime.fromisoformat(previous[0]) > now - timedelta(hours=1)
            ):
                return {
                    "mass_kg": None,
                    "status": "unavailable",
                    "reason": "No saved result; supplier retry available after one hour",
                }
            c.execute(
                "INSERT OR REPLACE INTO supplier_mass_attempts VALUES (?,?)",
                (revision_id, now.isoformat()),
            )
        result = json.loads(feed[0]) if feed else None
        if result is None and self.provider:
            try:
                result = self.provider.lookup(spec)
            except (OSError, ValueError):
                # Supplier failures never prevent S registration or association.
                result = None
        if result is None:
            return {
                "mass_kg": None,
                "status": "unavailable",
                "reason": "No verified supplier match; registration and association remain available",
            }
        result = {
            **result,
            "specification_key": key,
            "status": "supplier_reference",
            "retrieved_at": result.get("retrieved_at", now.isoformat()),
        }
        # Provider evidence is validated again independently of HTML parsing.
        if result["mass_kg"] != mass_kg(
            result["source_mass"], result["source_unit"], result["source_quantity"]
        ):
            raise ValueError("Inconsistent supplier mass evidence")
        source_url(result["source_url"])
        with self.database.transaction() as c:
            current = self._spec(c, user, revision_id)
            self.authorization.require_edit_revision(user, revision_id, c)
            self.revisions.require_checkout_owner(user, revision_id, c)
            if specification_key(current) != key:
                raise Conflict("Fastener specification changed during supplier lookup")
            saved = self._saved(c, revision_id, current)
            if saved:
                return saved
            c.execute(
                "INSERT INTO revision_reference_mass VALUES (?,?)", (revision_id, encode(result))
            )
            c.execute(
                "INSERT INTO audit_events(id,actor_id,event_type,entity_type,entity_id,occurred_at) VALUES (?,?,'standard.reference_mass_saved','ItemRevision',?,?)",
                (str(uuid4()), user.id, revision_id, now.isoformat()),
            )
        return result

    def import_csv(self, user, text):
        if user.role != "admin":
            raise Forbidden("Administrator access required to import supplier reference data")
        if not isinstance(text, str) or len(text.encode()) > 1024 * 1024:
            raise ValueError("CSV must be at most 1 MiB")
        reader = csv.DictReader(io.StringIO(text))
        if (
            reader.fieldnames is None
            or set(reader.fieldnames) != CSV_FIELDS
            or len(reader.fieldnames) != len(CSV_FIELDS)
        ):
            raise ValueError("CSV columns: " + ",".join(sorted(CSV_FIELDS)))
        records = {}
        now = datetime.now(UTC).isoformat()
        for row in reader:
            if len(records) >= 5000 or None in row or any(v is None for v in row.values()):
                raise ValueError("Invalid or oversized supplier CSV")
            spec = specification(json.loads(row["specification_json"]))
            key = specification_key(spec)
            if key in records:
                raise ValueError("Ambiguous duplicate specification in supplier CSV")
            if any(not row[k].strip() or len(row[k]) > 200 for k in ("supplier", "source_article")):
                raise ValueError("Supplier and article reference are required")
            records[key] = {
                "supplier": row["supplier"].strip(),
                "source_article": row["source_article"].strip(),
                "source_url": source_url(row["source_url"]),
                "source_mass": row["mass"],
                "source_unit": row["unit"],
                "source_quantity": row["quantity"],
                "mass_kg": mass_kg(row["mass"], row["unit"], row["quantity"]),
                "retrieved_at": now,
                "method": "supplier_csv",
            }
        if not records:
            raise ValueError("Supplier CSV is empty")
        with self.database.transaction() as c:
            for key, record in records.items():
                c.execute(
                    "INSERT OR REPLACE INTO supplier_mass_feed VALUES (?,?)", (key, encode(record))
                )
            c.execute(
                "INSERT INTO audit_events(id,actor_id,event_type,entity_type,entity_id,occurred_at) VALUES (?,?,'standard.reference_feed_imported','User',?,?)",
                (str(uuid4()), user.id, user.id, now),
            )
        return {"imported": len(records)}
