"""Local material assignment and mass evidence; no backend imports."""

import json
import math
from decimal import Decimal

from .mass_display import format_mass


def assign(document, metadata, revision_id, current, lines, mappings, engineering_properties=None):
    """Apply one undoable local proposal to explicitly selected final solids."""
    names = set()
    evidence = []
    total = Decimal(0)
    for obj, material_revision, density in mappings:
        if obj.Document is not document or obj.Name in names:
            raise ValueError("select distinct local final solids")
        names.add(obj.Name)
        shape = getattr(obj, "Shape", None)
        if shape is None or shape.isNull() or not shape.isValid() or not shape.Solids:
            raise ValueError("mass requires valid solid geometry")
        # Bodies and their features must not both be counted.
        for previous, _, _ in mappings:
            if previous is not obj and (
                previous in getattr(obj, "InListRecursive", [])
                or obj in getattr(previous, "InListRecursive", [])
            ):
                raise ValueError("select final solids without overlapping feature ancestry")
        density = Decimal(str(density))
        if not density.is_finite() or density <= 0 or not math.isfinite(shape.Volume):
            raise ValueError("invalid density or solid volume")
        for previous, _, _ in mappings:
            if previous is not obj and names and previous.Name in names:
                if shape.common(previous.Shape).Volume > 1e-7:
                    raise ValueError("selected solids overlap")
        volume = Decimal(str(shape.Volume))
        mass = volume * density / Decimal("1000000000")
        total += mass
        evidence.append(
            {
                "object_name": obj.Name,
                "material_revision_id": material_revision,
                "volume_mm3": str(volume),
                "density_kg_m3": str(density),
                "mass_kg": str(mass),
            }
        )
    payload = {
        "version": 1,
        "revision_id": revision_id,
        "expected_token": current["token"],
        "lines": lines,
        "mass_evidence": evidence,
    }
    document.openTransaction("Assign ForgePDM materials")
    try:
        for name in ("PDMMaterialInputs", "PDMFinishedMassKg"):
            if not hasattr(metadata, name):
                metadata.addProperty("App::PropertyString", name, "ForgePDM")
        if engineering_properties is not None:
            for name, key in (
                ("PDMDescription", "description"),
                ("PDMClassification", "classification"),
            ):
                if not hasattr(metadata, name):
                    metadata.addProperty("App::PropertyString", name, "ForgePDM")
                setattr(metadata, name, str(engineering_properties.get(key, "")))
        metadata.PDMMaterialInputs = json.dumps(payload, sort_keys=True)
        metadata.PDMFinishedMassKg = format_mass(total) if evidence else ""
        document.recompute()
        document.commitTransaction()
    except BaseException:
        document.abortTransaction()
        raise
    return payload


def refresh_mass(document, metadata):
    """Recompute saved evidence before upload; changed geometry invalidates old mass."""
    raw = getattr(metadata, "PDMMaterialInputs", "")
    if not raw:
        return
    value = json.loads(raw)
    mappings = []
    for record in value.get("mass_evidence", []):
        obj = document.getObject(record["object_name"])
        if obj is None:
            raise ValueError("material-mapped geometry was deleted; reassign materials")
        mappings.append((obj, record["material_revision_id"], record["density_kg_m3"]))
    assign(
        document,
        metadata,
        metadata.RevisionId,
        {"token": value["expected_token"]},
        value["lines"],
        mappings,
    )
