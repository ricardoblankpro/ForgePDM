"""Revision-bound supplier mass: explicit provenance, bounded lookup and CSV feed."""

import csv
import io
import json
import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from forgepdm.domain.entities import Conflict, Forbidden
from forgepdm.domain.reference_mass import (
    density_reference,
    estimate_mass,
    mass_kg,
    mass_token,
    source_url,
    specification_key,
)
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
            if value["specification_key"] == (specification_key(spec) if spec else None):
                return value
        return None

    @staticmethod
    def _public(value, spec, reason="No mass saved"):
        result = (
            dict(value) if value else {"mass_kg": None, "status": "unavailable", "reason": reason}
        )
        result["token"] = mass_token(value)
        reference = density_reference(spec)
        result["estimate_context"] = (
            {
                "geometry": spec["geometry"],
                "density_reference": reference,
                "specification_key": specification_key(spec),
            }
            if reference
            else None
        )
        return result

    def read(self, user, revision_id):
        with self.database.connection() as c:
            spec = self._spec(c, user, revision_id)
            return self._public(self._saved(c, revision_id, spec), spec)

    def save_fallback(self, user, revision_id, payload):
        """Save a client volume estimate or explicit manual entry under checkout."""
        now = datetime.now(UTC).isoformat()
        with self.database.transaction() as c:
            spec = self._spec(c, user, revision_id)
            self.authorization.require_edit_revision(user, revision_id, c)
            self.revisions.require_checkout_owner(user, revision_id, c)
            previous = self._saved(c, revision_id, spec)
            if payload.get("expected_token") != mass_token(previous):
                raise Conflict("Mass changed; reload before saving")
            if previous and previous["status"] == "supplier_reference":
                raise Conflict("A verified supplier reference is already saved")
            key = specification_key(spec) if spec else None
            method = payload.get("method")
            if method == "manual":
                if set(payload) != {"method", "mass_g", "note", "expected_token"}:
                    raise ValueError("Invalid manual mass fields")
                note = payload["note"]
                if not isinstance(note, str) or len(note) > 500:
                    raise ValueError("Mass note must be at most 500 characters")
                result = {
                    "status": "manual",
                    "mass_kg": mass_kg(payload["mass_g"], "g", 1),
                    "source_mass": str(payload["mass_g"]),
                    "source_unit": "g",
                    "source_quantity": "1",
                    "note": note.strip(),
                }
            elif method == "cad_estimate":
                if set(payload) != {
                    "method",
                    "expected_token",
                    "geometry",
                    "volume_mm3",
                    "shape_sha256",
                    "thread_mode",
                    "generator_version",
                }:
                    raise ValueError("Invalid CAD estimate fields")
                if previous:
                    # Automatic estimates never overwrite a manual value or a saved estimate.
                    return self._public(previous, spec)
                reference = density_reference(spec)
                if not reference:
                    raise ValueError("No reference density for the selected material")
                if payload["geometry"] != spec["geometry"]:
                    raise Conflict("CAD fastener geometry does not match the S specification")
                if not isinstance(payload["shape_sha256"], str) or not re.fullmatch(
                    r"[0-9a-f]{64}", payload["shape_sha256"]
                ):
                    raise ValueError("CAD shape hash is required")
                if payload["thread_mode"] not in ("simplified", "modeled", "unknown"):
                    raise ValueError("Invalid thread representation")
                version = payload["generator_version"]
                if not isinstance(version, str) or not version or len(version) > 100:
                    raise ValueError("Invalid generator version")
                result = {
                    "status": "cad_estimate",
                    "mass_kg": estimate_mass(payload["volume_mm3"], reference["density_kg_m3"]),
                    "volume_mm3": str(payload["volume_mm3"]),
                    "density_reference": reference,
                    "shape_sha256": payload["shape_sha256"],
                    "thread_mode": payload["thread_mode"],
                    "generator_version": version,
                    "measurement_source": "FreeCAD Fasteners Shape.Volume",
                }
            else:
                raise ValueError("Choose manual or cad_estimate mass")
            result.update(specification_key=key, recorded_at=now)
            c.execute(
                "INSERT OR REPLACE INTO revision_reference_mass VALUES (?,?)",
                (revision_id, encode(result)),
            )
            c.execute(
                "INSERT INTO audit_events(id,actor_id,event_type,entity_type,entity_id,occurred_at,details_json) VALUES (?,?,'standard.fallback_mass_saved','ItemRevision',?,?,?)",
                (
                    str(uuid4()),
                    user.id,
                    revision_id,
                    now,
                    encode({"before": previous, "after": result}),
                ),
            )
            return self._public(result, spec)

    def lookup(self, user, revision_id):
        # All network I/O happens outside DB transactions. Revalidate ownership,
        # lifecycle and specification before committing the result.
        now = datetime.now(UTC)
        with self.database.connection() as c:
            spec = self._spec(c, user, revision_id)
            saved = self._saved(c, revision_id, spec)
            if saved and saved["status"] != "cad_estimate":
                return self._public(saved, spec)
            if not spec:
                return self._public(saved, spec, "No structured fastener specification")
            try:
                self.authorization.require_edit_revision(user, revision_id, c)
                self.revisions.require_checkout_owner(user, revision_id, c)
            except (Conflict, Forbidden):
                return self._public(
                    saved, spec, "An owned Working checkout is required to save mass"
                )
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
                return self._public(
                    saved, spec, "No saved result; supplier retry available after one hour"
                )
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
            return self._public(
                saved, spec, "No verified supplier match; CAD/manual fallback is available"
            )
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
            if saved and saved["status"] != "cad_estimate":
                return self._public(saved, spec)
            c.execute(
                "INSERT OR REPLACE INTO revision_reference_mass VALUES (?,?)",
                (revision_id, encode(result)),
            )
            c.execute(
                "INSERT INTO audit_events(id,actor_id,event_type,entity_type,entity_id,occurred_at,details_json) VALUES (?,?,'standard.reference_mass_saved','ItemRevision',?,?,?)",
                (
                    str(uuid4()),
                    user.id,
                    revision_id,
                    now.isoformat(),
                    encode({"before": saved, "after": result}),
                ),
            )
        return self._public(result, spec)

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
