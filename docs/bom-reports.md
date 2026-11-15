# Shared engineering BOM views — addon 0.19.0 / schema 17

Use **BOM / Mass…** in FreeCAD or **Bill of materials** in the web GUI. Select
Direct, Indented or Flattened. All three views and the mass summary come from one
backend read snapshot. Switching views performs no engineering writes and does
not substitute newer component revisions. Use Refresh to fetch current stored
values; unsaved CAD changes are excluded.

| View | Rows and positions | Quantities |
|---|---|---|
| Direct | Immediate components, with stored BOM positions | Per one root assembly |
| Indented | All component occurrences, with stored position paths such as 5.9 | Both per immediate parent and accumulated per root |
| Flattened | P/S parts only, combined by exact component revision | Accumulated across all paths per root |

For three subassemblies with four screws each, plus two screws directly under
the root, the indented screw row has Qty / parent 4 and Qty / root 12. The direct
screw row has quantity 2. The flattened row has quantity 14. Different revisions
of the same screw stay separate. Repeated subassemblies remain separate branches
in Indented. Flattened positions are report row numbers, never stored BOM edits.
Material inputs and their units are not mixed into this engineering parts list.

## Mass and incomplete structure

Unit mass is for one component. Mass / root is unit mass multiplied by that row's
accumulated quantity. A subassembly's unit mass is its exact leaf rollup when all
required masses are available. **Do not sum parent and child masses in Indented**:
they overlap. The assembly summary counts each leaf occurrence once.

Missing mass appears as —, with an unavailable total and known subtotal. CAD
estimates keep the ~ marker, including subassemblies that contain estimates.
Empty subassemblies are structural issues, remain visible in Direct/Indented,
and are explicitly reported as missing from Flattened. No missing contribution
is presented as a complete zero total. FreeCAD lists missing reasons in its mass
summary; the web viewer has expandable issue details.

The service checks access to every traversed revision and fails the complete
report if any component is inaccessible. Cycles, invalid/excessive quantities,
more than 10,000 visited revisions or depth above 64 reject the report rather
than returning silently truncated totals. Decimal arithmetic preserves exact
quantity strings; clients only format masses for display.

## TechDraw

**Drawing BOM… → BOM view** selects the same server-generated rows. The layout
remembers the view alongside the editable title, columns and other settings.
The quantity column means Qty / root; an optional Qty / parent column is also
available. Item numbers are visually indented in Indented. The table still must
fit one page and is limited to 500 rows. Flattened generation is blocked when
empty subassemblies leave the structure unresolved; complete those stored BOMs
before generating that table. Missing part masses alone do not block generation.

Changing views does not copy custom annotations into unrelated rows. Direct
notes keep their original revision/position identity; indented notes follow the
full ancestor-revision/position path; flattened notes follow the exact revision
regardless of report renumbering. Other notes stay stored for recovery. Saved
SVG/report values remain frozen through reopening, retrieval and server changes.
Only explicit Update fetches fresh report values. No footer is added.

Legacy layouts/tables default to Direct. Non-direct tables use embedded format 2
so older addons refuse to update them; they remain ordinary native SVG symbols
viewable offline. Direct tables retain format 1. Install the new backend before
using addon 0.19.0, and refresh the web browser after upgrading.

## API and synchronization

`GET /api/v1/revisions/{revision_id}/bom-report` returns `views.direct`,
`views.indented`, `views.flattened`, a common evidence `token`, `generated_at`,
`mass`, `structure_complete` and `structure_issues`. Row provenance retains source
paths and flattened occurrences. `quantity`, `total_quantity` and `total_mass`
are per root; `quantity_per_parent` is null for aggregated rows.

The existing `/bom?recursive=true` contract still uses quantities per parent.
The old `/drawing-bom` endpoint projects Direct from the shared report, while
`/assembly-mass` projects its mass summary. No database migration is required.
CAD synchronization remains an independently reviewed replacement of the direct
engineering BOM. Viewer/report choices never rewrite stored positions or pins.

Design: [ADR-022](decisions/ADR-022-shared-bom-reports.md). Sheet splitting,
balloons, CAD-property columns and automatic publication gates remain future work.
