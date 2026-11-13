"""One read-snapshot report for a direct-component drawing engineering BOM."""

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal, localcontext

from forgepdm.application.bom import BOMService
from forgepdm.application.descriptions import DescriptionService
from forgepdm.application.physical_materials import PhysicalMaterialService
from forgepdm.application.reference_mass import ReferenceMassService
from forgepdm.domain.entities import Conflict


def drawing_bom(database, authorization, user, revision_id):
    with database.connection() as c, localcontext() as context:
        c.execute("BEGIN")
        context.prec = 4096
        authorization.require_read_revision(user, revision_id, c)
        root = c.execute(
            "SELECT r.id,r.label,i.number,i.kind FROM item_revisions r JOIN items i ON i.id=r.item_id WHERE r.id=?",
            (revision_id,),
        ).fetchone()
        if root["kind"] != "assembly":
            raise Conflict("Drawing BOM requires an assembly revision")
        lines = BOMService(database, authorization, None)._read_bom(
            c, user, revision_id, False, 1, set()
        )
        if len(lines) > 500:
            raise Conflict("Drawing BOM exceeds the 500 direct-line limit")
        for line in lines:
            rid = line["component_revision_id"]
            item = c.execute(
                "SELECT i.number_series,i.description FROM items i JOIN item_revisions r ON r.item_id=i.id WHERE r.id=?",
                (rid,),
            ).fetchone()
            text = DescriptionService.read_in(c, rid)["description"]
            line["description"] = text or item["description"]
            line["material"] = text if item["number_series"] == "P" else ""
            mass = {
                "mass_kg": None,
                "reason": "Subassembly unit mass is not included in this direct report",
            }
            if line["item_kind"] != "assembly":
                if item["number_series"] == "S":
                    service = ReferenceMassService(database, authorization, None)
                    spec = service._spec(c, user, rid)
                    mass = service._public(service._saved(c, rid, spec), spec)
                else:
                    mass = PhysicalMaterialService.mass_in(c, rid)
            quantity = Decimal(line["quantity"])
            if (
                not quantity.is_finite()
                or quantity <= 0
                or abs(quantity.adjusted()) > 30
                or len(quantity.as_tuple().digits) > 32
            ):
                raise Conflict("Invalid or excessive BOM quantity")
            line["mass_source"] = mass
            line["unit_mass"] = mass.get("mass_kg")
            line["total_mass"] = (
                str(Decimal(line["unit_mass"]) * Decimal(line["quantity"]))
                if line["unit_mass"] is not None
                else None
            )
        value = {
            "revision_id": revision_id,
            "item_number": root["number"],
            "revision_label": root["label"],
            "basis": "stored_direct_engineering_bom",
            "lines": lines,
        }
        value["token"] = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
        value["generated_at"] = datetime.now(UTC).isoformat()
        return value
