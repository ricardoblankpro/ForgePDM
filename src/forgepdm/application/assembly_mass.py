"""Read-only mass rollup of the exact stored engineering BOM."""

from decimal import Decimal, localcontext

from forgepdm.application.physical_materials import PhysicalMaterialService
from forgepdm.application.reference_mass import ReferenceMassService
from forgepdm.domain.entities import Conflict


class AssemblyMassService:
    def __init__(self, database, authorization):
        self.database = database
        self.authorization = authorization

    def read(self, user, revision_id):
        with self.database.connection() as c, localcontext() as context:
            # A single read snapshot covers BOM pins, permissions and source evidence.
            c.execute("BEGIN")
            context.prec = 4096
            leaves, issues = [], []
            visited = 0

            def walk(rid, quantity, path, ancestry):
                nonlocal visited
                visited += 1
                if visited > 10000 or len(path) > 64:
                    raise Conflict("Assembly mass exceeds traversal limits")
                self.authorization.require_read_revision(user, rid, c)
                row = c.execute(
                    "SELECT i.kind,i.number_series,i.number,r.label FROM item_revisions r "
                    "JOIN items i ON i.id=r.item_id WHERE r.id=?",
                    (rid,),
                ).fetchone()
                identity = {
                    "revision_id": rid,
                    "item_number": row["number"],
                    "revision_label": row["label"],
                    "quantity": str(quantity),
                    "path": path,
                }
                if rid in ancestry:
                    raise Conflict("Stored BOM contains a cycle")
                if row["kind"] == "assembly":
                    lines = c.execute(
                        "SELECT id,component_revision_id,quantity FROM bom_lines "
                        "WHERE parent_revision_id=? ORDER BY position",
                        (rid,),
                    ).fetchall()
                    if not lines:
                        issues.append({**identity, "reason": "Assembly has no stored BOM lines"})
                    for line in lines:
                        amount = Decimal(line["quantity"])
                        if (
                            not amount.is_finite()
                            or amount <= 0
                            or abs(amount.adjusted()) > 30
                            or len(amount.as_tuple().digits) > 32
                        ):
                            raise Conflict("Invalid or excessive BOM quantity")
                        walk(
                            line["component_revision_id"],
                            quantity * amount,
                            path + [line["id"]],
                            ancestry | {rid},
                        )
                    return
                if not path:
                    raise Conflict("Assembly mass requires an assembly revision")
                if row["number_series"] == "S":
                    svc = ReferenceMassService(self.database, self.authorization, None)
                    spec = svc._spec(c, user, rid)
                    mass = svc._public(svc._saved(c, rid, spec), spec)
                else:
                    mass = PhysicalMaterialService.mass_in(c, rid)
                if mass.get("mass_kg") is None:
                    issues.append({**identity, "reason": mass.get("reason", "Mass unavailable")})
                    return
                amount = Decimal(str(mass["mass_kg"]))
                if not amount.is_finite() or amount <= 0:
                    raise Conflict("Invalid stored component mass")
                leaves.append(
                    {
                        **identity,
                        "unit_mass_kg": str(amount),
                        "mass_kg": str(amount * quantity),
                        "source": mass,
                    }
                )

            walk(revision_id, Decimal(1), [], set())
            subtotal = sum((Decimal(v["mass_kg"]) for v in leaves), Decimal(0))
            return {
                "revision_id": revision_id,
                "basis": "stored_engineering_bom",
                "status": "incomplete" if issues else "complete",
                "mass_kg": None if issues else str(subtotal),
                "known_mass_kg": str(subtotal),
                "components": leaves,
                "issues": issues,
                "contains_cad_estimates": any(
                    v["source"].get("status") == "cad_estimate" for v in leaves
                ),
            }
