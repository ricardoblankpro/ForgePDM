"""Revision-bound material inputs and reproducible gross requirements."""

import hashlib
import json
import sqlite3
from contextlib import nullcontext
from datetime import UTC, datetime
from uuid import uuid4

from forgepdm.domain.entities import Conflict, NotFound
from forgepdm.domain.materials import UNITS, decimal_quantity, gross_requirement


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def token(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


EMPTY = {"lines": [], "readiness": "unreviewed", "reason": ""}


class MaterialService:
    def __init__(self, database, authorization, revisions):
        self.database, self.authorization, self.revisions = database, authorization, revisions

    def _revision(self, c, user, revision_id, edit=False):
        if edit:
            self.authorization.require_edit_revision(user, revision_id, c)
            self.revisions.require_checkout_owner(user, revision_id, c)
        else:
            self.authorization.require_read_revision(user, revision_id, c)
        return c.execute(
            "SELECT r.*,i.number,i.number_series,i.name AS item_name,i.description AS item_description FROM item_revisions r JOIN items i ON i.id=r.item_id WHERE r.id=?",
            (revision_id,),
        ).fetchone()

    def _read(self, c, revision_id):
        row = c.execute(
            "SELECT payload_json FROM material_boms WHERE revision_id=?", (revision_id,)
        ).fetchone()
        value = json.loads(row[0]) if row else dict(EMPTY)
        return {**value, "token": token(value)}

    def read(self, user, revision_id):
        with self.database.connection() as c:
            c.execute("BEGIN")
            self._revision(c, user, revision_id)
            return self._read(c, revision_id)

    def specification(self, user, revision_id):
        with self.database.connection() as c:
            self._revision(c, user, revision_id)
            row = c.execute(
                "SELECT specification_json FROM revision_material_data WHERE revision_id=?",
                (revision_id,),
            ).fetchone()
            value = json.loads(row[0]) if row else {}
            return {"specification": value, "token": token(value)}

    def save_specification(self, user, revision_id, specification, expected_token):
        # Identity describes interchangeable stock; purchase lengths are revision metadata.
        if not isinstance(specification, dict):
            raise ValueError("specification must be an object")  # noqa: TRY004
        allowed = {
            "grade",
            "standard",
            "form",
            "dimensions",
            "base_uom",
            "density_kg_m3",
            "description",
            "purchase_sizes",
            "attributes",
            "uom_conversions",
        }
        if set(specification) - allowed:
            raise ValueError("unknown material specification field")
        for key in ("grade", "standard", "form", "dimensions", "base_uom"):
            if not specification.get(key):
                raise ValueError(f"material {key} is required")
        if specification["base_uom"] not in {"ea", "m", "m2", "kg"}:
            raise ValueError("base UOM must be ea, m, m2 or kg")
        spec = dict(specification)
        spec["density_kg_m3"] = str(decimal_quantity(spec.get("density_kg_m3")))
        for key in ("grade", "standard", "form"):
            if not isinstance(spec[key], str) or len(spec[key]) > 200:
                raise ValueError("grade, standard and form must be bounded text")
            spec[key] = str(spec[key]).strip().upper()
        if not isinstance(spec["dimensions"], dict) or not spec["dimensions"]:
            raise ValueError("dimensions must contain named values in mm")
        spec["dimensions"] = {
            str(k).strip().lower(): str(decimal_quantity(v).normalize())
            for k, v in spec["dimensions"].items()
        }
        conversions = spec.get("uom_conversions", {})
        if not isinstance(conversions, dict) or any(
            unit not in {"ea", "m", "m2", "kg"} for unit in conversions
        ):
            raise ValueError(
                "conversion factors must map canonical units to the material base unit"
            )
        spec["uom_conversions"] = {
            unit: str(decimal_quantity(factor)) for unit, factor in conversions.items()
        }
        spec["description"] = str(
            spec.get("description")
            or " ".join(
                [
                    spec["form"],
                    spec["grade"],
                    spec["standard"],
                    *([f"{key}={value}MM" for key, value in spec["dimensions"].items()]),
                ]
            )
        ).upper()
        identity = encode(
            {k: spec[k] for k in ("grade", "standard", "form", "dimensions", "base_uom")}
        )
        if len(encode(spec)) > 32000:
            raise ValueError("specification too large")
        with self.database.transaction() as c:
            revision = self._revision(c, user, revision_id, True)
            if revision["number_series"] != "M":
                raise Conflict("material specifications require M items")
            old = c.execute(
                "SELECT specification_json FROM revision_material_data WHERE revision_id=?",
                (revision_id,),
            ).fetchone()
            if token(json.loads(old[0]) if old else {}) != expected_token:
                raise Conflict("specification changed; reload before editing")
            existing = c.execute(
                "SELECT identity_json FROM material_identities WHERE item_id=?",
                (revision["item_id"],),
            ).fetchone()
            if existing and existing[0] != identity:
                raise Conflict("identity changes require a new M item")
            try:
                c.execute(
                    "INSERT OR IGNORE INTO material_identities VALUES (?,?,?)",
                    (revision["item_id"], identity, spec["base_uom"]),
                )
                actual = c.execute(
                    "SELECT identity_json FROM material_identities WHERE item_id=?",
                    (revision["item_id"],),
                ).fetchone()
                if actual is None:
                    raise Conflict("material identity already exists")
            except sqlite3.IntegrityError as error:
                raise Conflict("material identity already exists") from error
            c.execute(
                "INSERT OR REPLACE INTO revision_material_data VALUES (?,?)",
                (revision_id, encode(spec)),
            )
            self._audit(c, user, revision_id, "material.specification_updated")
        return self.specification(user, revision_id)

    def replace(
        self,
        user,
        revision_id,
        lines,
        expected_token,
        readiness="unreviewed",
        reason="",
        connection=None,
    ):
        if readiness not in {"unreviewed", "complete", "not_applicable"}:
            raise ValueError("invalid readiness")
        if len(lines) > 1000 or len(reason) > 2000:
            raise ValueError("material BOM exceeds limits")
        if readiness == "complete" and not lines:
            raise ValueError("empty inputs require not_applicable with a reason")
        if readiness == "not_applicable" and (lines or not reason.strip()):
            raise ValueError("not applicable requires a reason and no lines")
        with (
            nullcontext(connection) if connection is not None else self.database.transaction()
        ) as c:
            parent = self._revision(c, user, revision_id, True)
            if parent["number_series"] not in ("P", "A"):
                raise Conflict("material inputs require P/A parents")
            if self._read(c, revision_id)["token"] != expected_token:
                raise Conflict("material BOM changed; reload before editing")
            prepared = []
            for index, line in enumerate(lines, 1):
                if (
                    not isinstance(line, dict)
                    or not {"component_revision_id", "quantity", "uom"} <= line.keys()
                ):
                    raise ValueError("input requires revision, quantity and unit")
                component = self._revision(c, user, line["component_revision_id"])
                if (
                    component["number_series"] not in ("M", "S")
                    or component["lifecycle_state"] == "obsolete"
                ):
                    raise Conflict("inputs must reference usable M/S revisions")
                if readiness == "complete" and component["lifecycle_state"] != "released":
                    raise Conflict("complete inputs require Released components")
                if (
                    component["number_series"] == "S"
                    and c.execute(
                        "SELECT 1 FROM bom_lines b JOIN item_revisions r ON r.id=b.component_revision_id WHERE b.parent_revision_id=? AND r.item_id=?",
                        (revision_id, component["item_id"]),
                    ).fetchone()
                ):
                    raise Conflict("purchased input already occurs in parent EBOM")
                unit = line["uom"]
                if unit not in UNITS:
                    raise ValueError("unsupported unit")
                base = "ea"
                if component["number_series"] == "M":
                    identity = c.execute(
                        "SELECT base_uom FROM material_identities WHERE item_id=?",
                        (component["item_id"],),
                    ).fetchone()
                    if identity is None:
                        raise Conflict("material specification is missing")
                    base = identity[0]
                if UNITS[unit][0] != base:
                    spec_row = c.execute(
                        "SELECT specification_json FROM revision_material_data WHERE revision_id=?",
                        (component["id"],),
                    ).fetchone()
                    conversion = (
                        json.loads(spec_row[0]).get("uom_conversions", {}).get(UNITS[unit][0])
                        if spec_row
                        else None
                    )
                    if conversion is None:
                        raise ValueError(
                            "input unit must match material base dimension or an explicit conversion"
                        )
                prepared.append(
                    {
                        "component_revision_id": component["id"],
                        "quantity": str(decimal_quantity(line["quantity"])),
                        "uom": unit,
                        "allowance_percent": str(
                            decimal_quantity(line.get("allowance_percent", 0), allow_zero=True)
                        ),
                        "position": index,
                        "note": str(line.get("note", ""))[:2000],
                    }
                )
            value = {"lines": prepared, "readiness": readiness, "reason": reason.strip()}
            c.execute(
                "INSERT OR REPLACE INTO material_boms VALUES (?,?,?,?)",
                (revision_id, encode(value), user.id, datetime.now(UTC).isoformat()),
            )
            c.execute("DELETE FROM material_bom_lines WHERE parent_revision_id=?", (revision_id,))
            c.executemany(
                "INSERT INTO material_bom_lines VALUES (?,?,?,?,?,?,?)",
                [
                    (
                        revision_id,
                        line["component_revision_id"],
                        line["position"],
                        line["quantity"],
                        line["uom"],
                        line["allowance_percent"],
                        line["note"],
                    )
                    for line in prepared
                ],
            )
            self._audit(c, user, revision_id, "material_bom.updated")
            return {**value, "token": token(value)}

    @staticmethod
    def _audit(c, user, revision_id, event):
        c.execute(
            "INSERT INTO audit_events(id,actor_id,event_type,entity_type,entity_id,occurred_at) VALUES (?,?,?,'ItemRevision',?,?)",
            (str(uuid4()), user.id, event, revision_id, datetime.now(UTC).isoformat()),
        )

    def calculate(self, user, roots, approved=False, save=False):
        if not roots or len(roots) > 100:
            raise ValueError("select 1 to 100 demand roots")
        rows, issues, sources = [], [], {}
        with self.database.transaction() as c:
            visits = 0

            def visit(revision_id, multiplier, path, ancestry, project):
                nonlocal visits
                visits += 1
                if visits > 10000 or len(ancestry) >= 64 or revision_id in ancestry:
                    raise Conflict("requirements cycle or traversal limit")
                r = self._revision(c, user, revision_id)
                path = path + [revision_id]
                if r["lifecycle_state"] != "released":
                    issues.append(f"{r['number']}: revision is not Released")
                if r["number_series"] in ("S", "M"):
                    unit = "ea"
                    if r["number_series"] == "M":
                        raise Conflict(
                            "select P/A/S demand roots; M consumption comes from material inputs"
                        )
                    rows.append(
                        {
                            "item_code": r["number"],
                            "revision_id": revision_id,
                            "revision_label": r["label"],
                            "description": r["item_description"] or r["item_name"],
                            "quantity": str(multiplier),
                            "uom": unit,
                            "path": path,
                            "project_context": project,
                        }
                    )
                    return
                inputs = self._read(c, revision_id)
                if inputs["readiness"] == "unreviewed":
                    issues.append(f"{r['number']}: material inputs unreviewed")
                ebom = [
                    dict(row)
                    for row in c.execute(
                        "SELECT component_revision_id,quantity,position FROM bom_lines WHERE parent_revision_id=? ORDER BY position",
                        (revision_id,),
                    )
                ]
                sources[revision_id] = {
                    "material_bom": inputs,
                    "ebom": ebom,
                    "revision_label": r["label"],
                    "item_code": r["number"],
                    "item_name": r["item_name"],
                    "catalog_description": r["item_description"],
                    "engineering_properties": self._properties(c, revision_id),
                    "cad_sources": [
                        dict(row)
                        for row in c.execute(
                            "SELECT d.id AS dataset_id,f.id AS file_id,f.content_hash,e.payload_json AS material_evidence FROM datasets d JOIN dataset_files df ON df.dataset_id=d.id JOIN files f ON f.id=df.file_id LEFT JOIN dataset_material_evidence e ON e.dataset_id=d.id WHERE d.revision_id=? AND d.dataset_type='native_cad' ORDER BY d.created_at,d.id",
                            (revision_id,),
                        )
                    ],
                }
                for line in inputs["lines"]:
                    component = self._revision(c, user, line["component_revision_id"])
                    if component["lifecycle_state"] != "released":
                        issues.append(f"{component['number']}: input is not Released")
                    quantity, unit = gross_requirement(
                        line["quantity"], line["uom"], multiplier, line["allowance_percent"]
                    )
                    spec = c.execute(
                        "SELECT specification_json FROM revision_material_data WHERE revision_id=?",
                        (component["id"],),
                    ).fetchone()
                    specification = json.loads(spec[0]) if spec else {}
                    base = specification.get("base_uom", "ea")
                    if unit != base:
                        factor = specification.get("uom_conversions", {}).get(unit)
                        if factor is None:
                            raise Conflict("input conversion is unavailable")
                        quantity *= decimal_quantity(factor)
                        unit = base
                    rows.append(
                        {
                            "item_code": component["number"],
                            "revision_id": component["id"],
                            "revision_label": component["label"],
                            "quantity": str(quantity),
                            "uom": unit,
                            "path": path + [component["id"]],
                            "project_context": project,
                            "specification": specification,
                        }
                    )
                for line in ebom:
                    visit(
                        line["component_revision_id"],
                        multiplier * decimal_quantity(line["quantity"]),
                        path,
                        ancestry | {revision_id},
                        project,
                    )

            normalized_roots = []
            for root in roots:
                q = decimal_quantity(root["quantity"])
                normalized_roots.append({**root, "quantity": str(q)})
                visit(root["root_revision_id"], q, [], set(), root.get("project_context"))
            totals = {}
            revisions = {}
            for row in rows:
                key = (row["item_code"], row["uom"])
                totals[key] = totals.get(
                    key, decimal_quantity(0, allow_zero=True)
                ) + decimal_quantity(row["quantity"])
                revisions.setdefault(key, set()).add(row["revision_id"])
            for key, ids in revisions.items():
                if len(ids) > 1:
                    issues.append(f"{key[0]}: mixed input revisions")
            revision_totals = {}
            for row in rows:
                key = (row["item_code"], row["revision_id"], row["uom"])
                revision_totals[key] = revision_totals.get(
                    key, decimal_quantity(0, allow_zero=True)
                ) + decimal_quantity(row["quantity"])
            issues = sorted(set(issues))
            if approved and issues:
                raise Conflict("requirements are not purchasing-ready: " + "; ".join(issues))
            result = {
                "schema_version": 1,
                "calculation_version": 1,
                "approved": approved,
                "roots": normalized_roots,
                "sources": sources,
                "lines": rows,
                "totals": [
                    {"item_code": key[0], "uom": key[1], "quantity": str(value)}
                    for key, value in sorted(totals.items())
                ],
                "issues": issues,
                "warnings": ["Duplicate demand roots are additive"]
                if len({r["root_revision_id"] for r in normalized_roots}) < len(normalized_roots)
                else [],
                "revision_totals": [
                    {"item_code": k[0], "revision_id": k[1], "uom": k[2], "quantity": str(v)}
                    for k, v in sorted(revision_totals.items())
                ],
            }
            result["fingerprint"] = token(result)
            if save:
                result["id"] = str(uuid4())
                c.execute(
                    "INSERT INTO requirement_snapshots VALUES (?,?,?,?)",
                    (result["id"], user.id, encode(result), datetime.now(UTC).isoformat()),
                )
            return result

    def snapshot(self, user, snapshot_id):
        with self.database.connection() as c:
            row = c.execute(
                "SELECT payload_json FROM requirement_snapshots WHERE id=?", (snapshot_id,)
            ).fetchone()
            if not row:
                raise NotFound("requirements snapshot not found")
            value = json.loads(row[0])
            for revision_id in value["sources"]:
                self._revision(c, user, revision_id)
            for line in value["lines"]:
                for revision_id in line["path"]:
                    self._revision(c, user, revision_id)
            for root in value["roots"]:
                self._revision(c, user, root["root_revision_id"])
            return value

    @staticmethod
    def _properties(c, revision_id):
        row = c.execute(
            "SELECT specification_json FROM revision_material_data WHERE revision_id=?",
            (revision_id,),
        ).fetchone()
        return json.loads(row[0]) if row else {}

    def save_properties(self, user, revision_id, properties, expected_token):
        if set(properties) - {"description", "classification", "attributes"}:
            raise ValueError("unknown engineering property")
        if len(encode(properties)) > 32000:
            raise ValueError("engineering properties exceed limits")
        if any(
            not isinstance(properties.get(key, ""), str)
            for key in ("description", "classification")
        ):
            raise ValueError("description and classification must be text")
        attributes = properties.get("attributes", {})
        if not isinstance(attributes, dict) or any(
            not isinstance(k, str) or not isinstance(v, (str, int, float, bool))
            for k, v in attributes.items()
        ):
            raise ValueError("attributes must be named scalar values")
        with self.database.transaction() as c:
            revision = self._revision(c, user, revision_id, True)
            if revision["number_series"] == "M":
                raise Conflict("edit raw materials through their specification")
            if token(self._properties(c, revision_id)) != expected_token:
                raise Conflict("engineering properties changed")
            c.execute(
                "INSERT OR REPLACE INTO revision_material_data VALUES (?,?)",
                (revision_id, encode(properties)),
            )
            existing = c.execute(
                "SELECT payload_json FROM material_boms WHERE revision_id=?", (revision_id,)
            ).fetchone()
            if existing:
                inputs = json.loads(existing[0])
                inputs["readiness"] = "unreviewed"
                c.execute(
                    "UPDATE material_boms SET payload_json=? WHERE revision_id=?",
                    (encode(inputs), revision_id),
                )
            self._audit(c, user, revision_id, "engineering_properties.updated")
        return self.specification(user, revision_id)

    def evidence(self, user, revision_id):
        with self.database.connection() as c:
            c.execute("BEGIN")
            self._revision(c, user, revision_id)
            current = self._read(c, revision_id)
            result = []
            for row in c.execute(
                "SELECT d.id AS dataset_id,f.content_hash,e.payload_json FROM datasets d JOIN dataset_files df ON df.dataset_id=d.id JOIN files f ON f.id=df.file_id LEFT JOIN dataset_material_evidence e ON e.dataset_id=d.id WHERE d.revision_id=? AND d.dataset_type='native_cad' ORDER BY d.created_at DESC,d.id DESC",
                (revision_id,),
            ):
                value = json.loads(row["payload_json"]) if row["payload_json"] else {}
                records = value.get("mass_evidence", [])
                mass = (
                    sum(
                        (
                            decimal_quantity(record["mass_kg"], allow_zero=True)
                            for record in records
                        ),
                        decimal_quantity(0, allow_zero=True),
                    )
                    if records
                    else None
                )
                result.append(
                    {
                        "dataset_id": row["dataset_id"],
                        "content_hash": row["content_hash"],
                        "mass_kg": str(mass) if mass is not None else None,
                        "method": "client_selected_solids",
                        "stale_inputs": value.get("canonical_lines") != current["lines"],
                        "objects": records,
                    }
                )
            return result
