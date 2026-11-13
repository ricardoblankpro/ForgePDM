# Engineering BOM tables — addon 0.18.0

1. Open the managed assembly working copy and use **Check Out / Renew**.
2. Create a TechDraw page/template if needed.
3. Choose **ForgePDM → BOM and publishing → Drawing BOM…**.
4. Select a page and New table, configure columns or load a layout, then press OK.
5. Save/upload/check in explicitly when ready. The command only changes the local
   drawing; it does not publish CAD or synchronize the server BOM.

Rows come from the **stored direct engineering BOM**. Use BOM / Mass to review and
synchronize CAD changes first when necessary. Empty stored BOMs cannot generate a
table. Subassemblies remain direct lines; their contents are not expanded.

## Columns and custom text

Default: Pos., Item number, Revision, Qty., Description / Material. Purchased/standard
items without a description use their saved purchasing designation. P/A names are
not forced into this default column. Add/remove
columns, change headings/widths/alignment, move columns up/down and set text size.
Optional fields include name/designation, material, lifecycle, type, unit/extended mass and custom
text columns. Mass units can be kg or g with 0–6 decimal places. Unknown mass is
shown as — and CAD estimates as ~. Direct subassembly unit mass is unavailable in
this first report; no incomplete total is presented as zero.

Press **Preview / edit custom text** after editing the column definition. Generated
cells are read-only; edit custom text cells directly. Custom values follow the
component revision + BOM position + column identity through updates/reordering.
Changed revisions/positions do not inherit unrelated text; the previous entries
remain in the table data. Up to 12 columns, 30 local named layouts and 500 direct
report lines are supported; the table must fit one page. Text values are bounded.

**Save layout as…** stores a reusable definition, without component values or row
notes, in local FreeCAD preferences. The drawing also stores its own layout and
values, so another workstation can view and update the table without the preset.

## Placement and update

X/Y specify the table centre in page millimetres. The editor reports its size and
keeps page-fit errors open for correction. Reduce font/widths or move the centre
if necessary. Use native TechDraw positioning after insertion as well.

Select a generated table, then run **Drawing BOM…** to update it. Alternatively
select it from the Table selector. Updates preserve placement, scale/rotation,
column settings and matching custom text. If published data, permissions or
checkout change during review, the command rejects the proposal; reopen to review.

The table contains a frozen report and embedded SVG. Saving/reopening or downloading
an older snapshot keeps those exact values, even if the Working server BOM later
changes. The table remains viewable offline without ForgePDM code. There is no
background refresh and no automatic stale-table check at release/PDF publication:
explicitly update and publish the intended drawing snapshot.

The title is currently ENGINEERING BOM and the font family DejaVu Sans; headings,
text size, alignment and mass formatting are configurable. Other fonts/platforms
may render differently and have not received the same acceptance coverage.

## Delivery and future increments

Requires the updated backend's `/api/v1/revisions/{id}/drawing-bom` read endpoint;
restart the backend when upgrading. Database schema remains 17. No engineering
records are backfilled. Embedded pages use the existing upload/reconstruction and
source-pinned PDF publication workflow.

Flattened/indented views, table splitting across sheets, native CAD-property
columns and balloon integration remain future increments. See ADR-021 and the
current development handoff for validation and installation evidence.
