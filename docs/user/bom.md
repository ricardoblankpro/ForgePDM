# BOM views and assembly mass

Use **BOM / Mass…** in FreeCAD or **Bill of materials** in the web workspace.
Direct, Indented and Flattened rows and the mass summary come from one server
read snapshot of the stored engineering BOM. Refresh fetches new evidence;
changing views does not write engineering data or adopt newer revisions.

| View | Rows and positions | Quantity |
|---|---|---|
| Direct | Immediate components, stored BOM positions | Per one root assembly |
| Indented | Repeated occurrences and nested stored position paths, such as 5.9 | Per immediate parent and accumulated per root |
| Flattened | P/S leaves combined by exact component revision | Accumulated across all paths per root |

Three subassemblies containing four screws each, plus two screws directly under
the root, show 4 per parent and 12 per root on the nested row, 2 on the direct
screw row, and 14 in Flattened. Different revisions stay separate. Flattened
positions are generated report indices, not edits to stored BOM positions.
Material-input units are not mixed into engineering component counts.

## Mass

Unit mass describes one component. Mass / root multiplies it by the accumulated
quantity for that row. A subassembly has unit mass when its leaf rollup is
complete. **Indented parent and child masses overlap; do not add them together.**
The overall assembly summary counts each leaf occurrence once.

Unknown mass appears as —, with an unavailable total and a known subtotal.
CAD estimates retain a ~ marker, including rolled-up subassemblies. Empty
subassemblies remain visible in Direct/Indented and are explicit structural
issues in Flattened. No missing contribution becomes a complete zero total.
FreeCAD lists missing reasons; the web viewer has expandable issue details.

Reports require read access to every traversed revision. An inaccessible child,
cycle, invalid/excessive quantity, more than 10,000 visits or depth above 64
rejects the report rather than returning silently truncated totals. Quantities
retain Decimal precision; display rounding does not change calculations.

## Review changes from CAD

1. Save/upload the assembly and changed managed components. Hold an owned
   Working checkout and open the intended managed working copy.
2. Choose **Update from CAD** in BOM / Mass. Supported candidates are included
   by default. **Choose components…** optionally excludes occurrences; old
   custom exclusions cannot be inferred automatically.
3. Review the stored and proposed direct lines, quantities and positions. Apply
   once. Exact no-ops disable Apply; removals, reductions, empty replacements
   and custom/split-position changes require confirmation.
4. The viewer refreshes after Apply. Closing without applying preserves the BOM.

Synchronization replaces the direct engineering BOM, regardless of the selected
report view. It is independent of native Upload/Check In. Revision pins, saved
snapshot evidence, document/session state, checkout and optimistic server tokens
are revalidated. A failed/stale proposal must be prepared again; it is not
retried automatically. Inspect manually maintained lines before replacement.

[TechDraw tables](drawings.md) freeze these same rows in the drawing. Complete
subassembly BOMs before attempting a flattened drawing with unresolved structure.
See [API contracts](../development/api.md) for the read-only report shape.
