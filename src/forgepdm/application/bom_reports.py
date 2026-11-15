"""Revision-pinned BOM presentations and one leaf-mass rollup per read snapshot."""

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, localcontext

from forgepdm.application.descriptions import DescriptionService
from forgepdm.application.physical_materials import PhysicalMaterialService
from forgepdm.application.reference_mass import ReferenceMassService
from forgepdm.domain.entities import Conflict

VIEWS = ("direct", "indented", "flattened")
MAX_NODES = 10000
MAX_DEPTH = 64


def project_report(report, view):
    if view not in VIEWS:
        raise ValueError("BOM view must be direct, indented or flattened")
    return {
        **{k: v for k, v in report.items() if k != "views"},
        "view": view,
        "basis": "stored_direct_engineering_bom" if view == "direct" else "stored_engineering_bom",
        "lines": report["views"][view],
    }


def _quantity(value):
    try:
        amount = Decimal(value)
    except (InvalidOperation, ValueError, TypeError) as error:
        raise Conflict("Invalid or excessive BOM quantity") from error
    if (
        not amount.is_finite()
        or amount <= 0
        or abs(amount.adjusted()) > 30
        or len(amount.as_tuple().digits) > 32
    ):
        raise Conflict("Invalid or excessive BOM quantity")
    return amount


def bom_report(database, authorization, user, revision_id):
    with database.connection() as connection, localcontext() as context:
        connection.execute("BEGIN")
        context.prec = 4096
        return read_in(connection, database, authorization, user, revision_id)


def read_in(c, database, authorization, user, revision_id):
    metadata, sources, children = {}, {}, {}
    indented, leaves, issues, structure_issues = [], [], [], []
    visited = 0

    def identity(rid):
        if rid not in metadata:
            authorization.require_read_revision(user, rid, c)
            row = c.execute(
                "SELECT i.id AS item_id,i.number AS item_number,i.kind AS item_kind,"
                "i.name AS item_name,i.number_series,i.description AS fallback_description,"
                "r.label AS revision_label,r.lifecycle_state FROM item_revisions r "
                "JOIN items i ON i.id=r.item_id WHERE r.id=?",
                (rid,),
            ).fetchone()
            if row["number_series"] not in ("P", "A", "S"):
                raise Conflict("Engineering BOM contains an unsupported item series")
            text = DescriptionService.read_in(c, rid)["description"]
            metadata[rid] = {
                key: row[key]
                for key in (
                    "item_id",
                    "item_number",
                    "item_kind",
                    "item_name",
                    "revision_label",
                    "lifecycle_state",
                )
            }
            metadata[rid].update(
                description=text or row["fallback_description"],
                material=text if row["number_series"] == "P" else "",
                number_series=row["number_series"],
            )
        return metadata[rid]

    root = identity(revision_id)
    if root["item_kind"] != "assembly":
        raise Conflict("BOM report requires an assembly revision")

    def walk(rid, total, path, positions, revision_path, ancestry, row=None):
        nonlocal visited
        visited += 1
        if visited > MAX_NODES or len(path) > MAX_DEPTH:
            raise Conflict("BOM report exceeds traversal limits")
        if rid in ancestry:
            raise Conflict("Stored BOM contains a cycle")
        item = identity(rid)
        evidence = {
            "revision_id": rid,
            "item_number": item["item_number"],
            "revision_label": item["revision_label"],
            "quantity": str(total),
            "path": path,
        }
        known, complete, estimated = Decimal(0), True, False
        if item["item_kind"] == "assembly":
            if rid not in children:
                children[rid] = c.execute(
                    "SELECT id,component_revision_id,quantity,position FROM bom_lines "
                    "WHERE parent_revision_id=? ORDER BY position",
                    (rid,),
                ).fetchmany(MAX_NODES + 1)
            if not children[rid]:
                issue = {**evidence, "reason": "Assembly has no stored BOM lines"}
                issues.append(issue)
                structure_issues.append(issue)
                complete = False
            for line in children[rid]:
                amount = _quantity(line["quantity"])
                child_id = line["component_revision_id"]
                child_positions = positions + [line["position"]]
                child_revisions = revision_path + [rid]
                key = "indented:" + json.dumps(
                    [child_revisions, child_positions, child_id], separators=(",", ":")
                )
                child = {
                    **identity(child_id),
                    "id": line["id"],
                    "parent_revision_id": rid,
                    "component_revision_id": child_id,
                    "row_key": key,
                    "parent_key": row["row_key"] if row else None,
                    "position": ".".join(map(str, child_positions)),
                    "bom_position": line["position"],
                    "position_path": child_positions,
                    "level": len(child_positions),
                    "quantity_per_parent": str(amount),
                    "quantity": str(total * amount),
                    "total_quantity": str(total * amount),
                    "path": path + [line["id"]],
                }
                indented.append(child)
                child_known, child_complete, child_estimated = walk(
                    child_id,
                    total * amount,
                    child["path"],
                    child_positions,
                    child_revisions,
                    ancestry | {rid},
                    child,
                )
                known += child_known * amount
                complete &= child_complete
                estimated |= child_estimated
            source = {
                "status": "cad_estimate" if estimated else "complete" if complete else "incomplete",
                "basis": "stored_engineering_bom",
                "mass_kg": str(known) if complete else None,
                "known_mass_kg": str(known),
                "contains_cad_estimates": estimated,
                "reason": "" if complete else "Subassembly mass is incomplete; see report issues",
            }
        else:
            if rid not in sources:
                if item["number_series"] == "S":
                    service = ReferenceMassService(database, authorization, None)
                    spec = service._spec(c, user, rid)
                    sources[rid] = service._public(service._saved(c, rid, spec), spec)
                else:
                    sources[rid] = PhysicalMaterialService.mass_in(c, rid)
            source = sources[rid]
            complete = source.get("mass_kg") is not None
            if complete:
                try:
                    known = Decimal(str(source["mass_kg"]))
                except InvalidOperation as error:
                    raise Conflict("Invalid stored component mass") from error
                if not known.is_finite() or known <= 0:
                    raise Conflict("Invalid stored component mass")
                estimated = source.get("status") == "cad_estimate"
                leaves.append(
                    {
                        **evidence,
                        "unit_mass_kg": str(known),
                        "mass_kg": str(known * total),
                        "source": source,
                    }
                )
            else:
                issues.append({**evidence, "reason": source.get("reason", "Mass unavailable")})
        if row is not None:
            row.update(
                unit_mass=str(known) if complete else None,
                total_mass=str(known * total) if complete else None,
                known_total_mass=str(known * total),
                mass_source=source,
            )
        return known, complete, estimated

    known, complete, estimated = walk(revision_id, Decimal(1), [], [], [], set())
    direct, flattened = [], {}
    for row in indented:
        if row["level"] == 1:
            direct.append(
                {
                    **row,
                    "position": row["bom_position"],
                    "row_key": row["component_revision_id"] + ":" + str(row["bom_position"]),
                    "parent_key": None,
                }
            )
        if row["item_kind"] == "assembly":
            continue
        rid = row["component_revision_id"]
        if rid not in flattened:
            flattened[rid] = {
                **row,
                "id": "flattened:" + rid,
                "row_key": "flattened:" + rid,
                "parent_key": None,
                "parent_revision_id": None,
                "level": 1,
                "quantity_per_parent": None,
                "occurrences": [],
            }
        flattened[rid]["occurrences"].append(
            {
                "path": row["path"],
                "position_path": row["position_path"],
                "parent_revision_id": row["parent_revision_id"],
                "quantity_per_parent": row["quantity_per_parent"],
                "total_quantity": row["total_quantity"],
            }
        )
    flat_rows = sorted(
        flattened.values(),
        key=lambda row: (row["item_number"], row["revision_label"], row["component_revision_id"]),
    )
    for position, row in enumerate(flat_rows, 1):
        amount = sum((Decimal(v["total_quantity"]) for v in row["occurrences"]), Decimal(0))
        row.update(
            position=position,
            bom_position=None,
            position_path=[],
            path=[],
            quantity=str(amount),
            total_quantity=str(amount),
        )
        row["total_mass"] = (
            str(Decimal(row["unit_mass"]) * amount) if row["unit_mass"] is not None else None
        )
        row["known_total_mass"] = row["total_mass"] or "0"
    result = {
        "revision_id": revision_id,
        "item_number": root["item_number"],
        "revision_label": root["revision_label"],
        "basis": "stored_engineering_bom",
        "quantity_basis": "per_root_assembly",
        "structure_complete": not structure_issues,
        "structure_issues": structure_issues,
        "mass": {
            "revision_id": revision_id,
            "basis": "stored_engineering_bom",
            "status": "complete" if complete else "incomplete",
            "mass_kg": str(known) if complete else None,
            "known_mass_kg": str(known),
            "components": leaves,
            "issues": issues,
            "contains_cad_estimates": estimated,
        },
        "views": {"direct": direct, "indented": indented, "flattened": flat_rows},
    }
    result["token"] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    result["generated_at"] = datetime.now(UTC).isoformat()
    return result
