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

Configure columns, headings, order, widths, alignment and font size. Default
columns are position, item, revision, Qty / root and Description / Material.
Optional columns include quantity per parent, material, type, lifecycle,
unit/extended mass and custom text. Mass can use kg/g and 0–6 decimals; unknown
and estimated values keep their markers. The font family is currently fixed.

**Preview / edit custom text** makes custom cells editable; generated cells remain
read-only. Up to 12 columns, 500 rows and 30 local named layouts are supported.
Layouts retain view/title/settings but no row notes. Each drawing embeds its own
layout/report/notes, so another workstation does not need the local preset.

One table must fit one page. X/Y specify its centre in page millimetres. Correct
fit errors by changing widths/font/position. Indented item columns need enough
width for their depth. Flattened generation is blocked by unresolved empty
subassemblies; missing part mass alone does not block it. Sheet splitting,
balloons, arbitrary CAD-property columns and stale-publication gates are deferred.

Select a generated table and reopen Drawing BOM to update it. Updates retain
placement, scale/rotation and matching annotations. Direct notes follow exact
revision + stored position; indented notes follow the complete ancestor/position
path; flattened notes follow the exact component revision across renumbering.
Notes do not leak between views. Orphaned entries remain saved for recovery.

The table is a native embedded SVG symbol with frozen report data. Reopen,
recompute and retrieval do not fetch new server values. Direct/legacy tables use
format 1; non-direct tables use format 2 so older addons refuse their update.
Both remain viewable offline without ForgePDM. Active CAD edit mode, changed
permissions/lease or stale report evidence rejects insertion/update.

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
