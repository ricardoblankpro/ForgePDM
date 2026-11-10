# ADR-017: Derive assembly mass from the stored engineering BOM

Date: 2026-11-09. Status: accepted implementation.

Compute finished assembly mass in the backend from exact revision-pinned EBOM
paths, multiplying Decimal quantities and reusing validated published P mass and
saved S mass. Read all evidence and permissions in one database snapshot. Expose
one read-only API to the web Description tab and FreeCAD Show BOM.

Do not infer a zero for unknown children or empty subassemblies: return an
unavailable total, a known subtotal and per-path reasons. Preserve source evidence,
including approximation warnings. Deny the whole request for an inaccessible child.
Bound traversal and arithmetic; detect cycles defensively.

This avoids FreeCAD-specific geometry traversal in business logic, double counting
subassembly geometry, network enrichment during reads and changes to existing
revision/BOM rules. No new persistence or migration is needed. Manufacturing inputs
are outside finished EBOM mass. Calculations are current reports over pinned
revisions, not immutable historical certificates: Working revision content remains
mutable. Immutable mass publication is a separate future decision.
