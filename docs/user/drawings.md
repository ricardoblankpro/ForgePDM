# TechDraw tables and PDF publication

Drawings belong to managed CAD snapshots. A table update changes local CAD;
PDF publication is a separate, explicit operation against an uploaded source.

## Insert or update a BOM table

1. Open the assembly's managed Working copy and use **Check Out / Renew**.
2. Create a TechDraw page/template, then choose **ForgePDM → BOM and publishing
   → Drawing BOM…**.
3. Select the page and a new/existing table. Choose Direct, Indented or Flattened
   from **BOM view**. Rows use the [stored report](bom.md), not unsaved CAD edits.
4. Configure the table, preview, then accept. Save/upload/check in explicitly
   when ready. This command does not synchronize the server BOM.

The title is editable up to 300 characters. Optional `{item_number}` and
`{revision_label}` placeholders follow the report on explicit Update. Leave the
title blank to hide it. No footer is generated. Existing saved tables keep
previous contents until explicitly updated.

**Sort by** defaults to **Item number**, ascending, for new tables. Choose
BOM position, Description / Material, Quantity / root, Unit mass or Mass / root,
and ascending/descending order. Quantities and masses sort numerically; unknown
values stay last. Text sorting ignores case/accents and compares embedded numbers
naturally (P2 before P10). Equal values retain their stored BOM order.

Indented tables sort siblings while keeping children with their parent. Sorting
does not renumber BOM positions or change quantities, source evidence or notes.
Choose **Stored BOM order** to keep the report's original ordering. Older tables
and layouts without a sort setting retain that order until explicitly changed.

Configure columns, headings, column order, widths, alignment and font size. Default
columns are position, item, revision, Qty / root and Description / Material.
Optional columns include quantity per parent, material, type, lifecycle,
unit/extended mass and custom text. Mass can use kg/g and 0–6 decimals; unknown
and estimated values keep their markers. The font family is currently fixed.

**Preview / edit custom text** makes custom cells editable; generated cells remain
read-only. Up to 12 columns, 500 rows and 30 local named layouts are supported.
Layouts retain view/title/sort/settings but no row notes. Each drawing embeds its own
layout/report/notes, so another workstation does not need the local preset.

One table must fit one page. X/Y specify its centre in page millimetres. Correct
fit errors by changing widths/font/position. Indented item columns need enough
width for their depth. Flattened generation is blocked by unresolved empty
subassemblies; missing part mass alone does not block it. Sheet splitting,
arbitrary CAD-property columns and stale-publication gates are deferred. Direct
table balloon links are available as described below.

Select a generated table and reopen Drawing BOM to update it. Updates retain
placement, scale/rotation and matching annotations. Direct notes follow exact
revision + stored position; indented notes follow the complete ancestor/position
path; flattened notes follow the exact component revision across renumbering.
Notes do not leak between views. Orphaned entries remain saved for recovery.

The table is a native embedded SVG symbol with frozen report data. Reopen,
recompute and retrieval do not fetch new server values. Localized tables use format 3 and freeze language and translation provenance;
see [description languages](localization.md). Direct/legacy tables use
format 1; non-direct tables use format 2 so older addons refuse their update.
Explicitly sorted tables use format 4 and retain the same frozen language and
provenance when present. Older addons can display their embedded SVG but reject
updates they cannot preserve. Linked tables use format 5 so older addons refuse
updates that cannot maintain balloon links. Automatic attachments use format 6. Formats 1–6 remain viewable offline
without ForgePDM. Active CAD edit mode, changed
permissions/lease or stale report evidence rejects insertion/update.

## Automatic balloons from connected geometry

With a managed Working assembly checked out and a Direct Drawing BOM on the page,
create a balloon with the normal **TechDraw → Insert Balloon Annotation** tool.
After placement finishes, ForgePDM identifies the touched managed component and
fills in its existing **BOM Position**. Moving the arrow to another component
retargets the link; moving only the bubble preserves it.

Ordinary orthographic/isometric and projection-group views are supported. The
arrow must touch geometry or be inside its projected solid region, within 0.25 mm
on paper. Overlapping/occluded components and split BOM entries require a chooser;
ForgePDM does not guess which component is intended. Each choice also shows the
frozen BOM description (or item name when absent), using the table's saved language. Multiple compatible tables
require a table choice unless the balloon already has a compatible target.

Unmanaged geometry or a component absent from the frozen BOM cannot be assigned.
Update the table if needed, then select the balloon and use **Link BOM Balloon… →
Automatic from arrow** to retry. Ambiguous cancellation/resolution failure shows
**?**. Without a valid session, permission and owned live checkout, automatic CAD
changes are withheld; log in and retry explicitly.

Undo the automatic linking transaction separately from the native placement/drag.
Undo/redo does not immediately rerun detection. Reopening a drawing does not adopt
old balloons. Automatic attachments use table format 6 and retain frozen geometry
and view evidence; changed attachments block ForgePDM PDF rendering until corrected.
Save/upload explicitly. Section, detail, broken and perspective views use manual
linking below. CAD-derived engineering BOM changes remain separately reviewed.

## Link a balloon to a BOM entry

1. Check out the assembly's managed Working copy. Create and position a native
   TechDraw balloon using the TechDraw workbench.
2. Select that balloon and choose **ForgePDM → BOM and publishing → Link BOM
   Balloon…**, then **Manual entry** when prompted. You can also choose a balloon within the dialog.
3. Choose the page, balloon and a **Direct** ForgePDM table on that page. Select
   the intended entry using its BOM Position, item number, revision and description.
4. Accept to replace the balloon text/expression with the frozen **BOM Position**.
   Save and upload explicitly when ready.

Leader placement, arrow and bubble style are retained. Several balloons can link
to one entry; repeated components at different positions are separate entries.
The link survives sorting, language changes, save/reopen and offline display.
Sorting never assigns new sequential drawing numbers. Existing literal balloons
stay unlinked until explicitly adopted.

An explicit Drawing BOM update changes its linked balloon text in the same undo
transaction. Missing, renumbered or replaced revisions and changed duplicate-entry
sets display **?** and an **Unresolved** property. The editor previews affected
balloons and the update warns you. Use **Link BOM Balloon…** again to explicitly
select the correct current entry. Returning an old entry does not automatically
repair an unresolved link. A deleted table leaves an orphan link; relink it to a
valid table or delete the unwanted balloon.

ForgePDM blocks new PDF rendering when an adopted balloon on a selected page has
an invalid/orphan link or inconsistent expression/text in the uploaded snapshot.
Correct the links and save/upload before retrying publication. Regular TechDraw
exports remain native. Previously published PDFs and recovery of already-frozen
publication bundles are unchanged.

Both workflows support Direct tables. Indented and Flattened balloon links,
automatic bubble placement and physical leader reattachment are deferred. Native metadata provides entry continuity, not individual
physical-instance tracking between identical components.

## Embedded pages and templates

Managed native snapshots retain supported TechDraw pages and their embedded
resources. Template fields are frozen into self-contained copies; a missing
original template path does not justify substituting newer engineering data.
External resources and unsupported SVG references are rejected rather than
silently reconstructed from arbitrary paths. Use managed retrieval to restore
an exact drawing configuration.

## Publish PDFs

Save and upload the intended source snapshot first. With an owned Working
checkout, choose **Publish Drawing PDFs…**, select pages and review the exact
uploaded source. Export happens from verified isolated copies. Original
engineering documents, selection and checkout are preserved; publication does
not automatically check in or synchronize the BOM.

The web **Drawings** tab lists publications for the selected revision, supports
PDF preview/download and warns when a newer native snapshot exists. Later
uploads do not rewrite previous PDFs. Released revisions keep their original
publications; a new revision has a separate list. Explicitly update the intended
BOM table before publishing: no automatic stale-table gate is implemented.

After a timeout, retry publication to recover the original frozen bundle rather
than rendering newer local edits into an old operation. Keep journals with
workspace backups. A publication supports 1–32 pages, at most 25 MiB per PDF and
100 MiB total. Combined PDFs, server rendering and automatic publication during
check-in are deferred. Source associations attest to the client's verified
rendering input, not a server-side regeneration of CAD geometry.
