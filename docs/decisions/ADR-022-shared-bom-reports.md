# ADR-022 — Shared direct, indented and flattened engineering BOM reports

Status: implemented in addon 0.19.0, 2026-11-15.

Add a read-only report over one SQLite read snapshot, separate from BOM editing.
The report supplies three server-generated views to FreeCAD, web and TechDraw.
Existing BOM mutation/snapshot contracts and exact revision pins do not change.

Direct rows retain stored positions. Indented rows use stored position paths and
retain both quantity per immediate parent and cumulative quantity per one root
assembly. Flattened rows include P/S leaves only, grouped by exact revision ID;
their positions are report indices, not persisted BOM positions. All report
`quantity` and `total_mass` fields refer to one root assembly. Explicit
`quantity_per_parent` and `total_quantity` fields avoid ambiguity. Quantity units
remain the existing engineering component counts; material-input units are not
mixed into this report.

Traverse exact pins with Decimal arithmetic, permission checks on every visited
revision, cycle detection and bounded depth/node counts. Fail the entire report
on inaccessible descendants or exceeded limits. Empty assemblies remain visible
in direct/indented views and appear in structural issues; flattening never calls
them parts or silently claims completeness. Block flattened drawing generation
until their structure is supplied. Unknown mass remains unavailable with a known
subtotal. A single shared leaf rollup supplies overall mass; indented parent and
child masses are not added together. Complete subassembly unit masses use the
same evidence. Preserve CAD estimate markers through rolled-up subassemblies.

Return all views from one snapshot, with a common evidence token, timestamp,
source occurrences, structural issues and mass summary. Clients only select
server rows; they never perform quantity multiplication or aggregation. Keep the
old drawing-report route as a direct projection of this shared implementation.

Deliver backend first, then FreeCAD/web viewers, then drawing view selection.
View switches are local selections of one fetched report, with explicit refresh.
Keep synchronization as an independently reviewed direct-BOM replacement.
Drawing layouts remember the view; saved SVG/report data stay frozen. Legacy
tables/layouts default to direct. Annotation keys include the full revision and
position path for indented rows, and a separate exact-revision key for flattened
rows, preventing notes from leaking between presentations. Direct row keys retain
their existing identity. Orphaned annotations are retained for recovery.

Non-direct drawing tables use embedded format 2 so older addons reject their
update rather than silently converting them to direct rows. Direct tables keep
format 1. Both remain ordinary embedded SVG symbols readable without the addon.

Multi-sheet splitting, balloons, CAD-property mapping and automatic publication
gates remain separate increments. This does not add a schema migration.
