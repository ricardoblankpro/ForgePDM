# ADR-030 — Automatic balloon attachment resolution

Status: accepted, 2026-11-20. Extends ADR-029 following the owner's request to
use normal TechDraw balloons and follow the connected component when its arrow moves.

[ADR-031](ADR-031-stable-balloon-geometry-evidence.md) extends the evidence contract
with stable version-3 attachments and format-7 tables; the legacy contract below
remains supported.

A deferred document observer handles newly placed native balloons and changes to
OriginX/OriginY/SourceView. It ignores restoration, bubble X/Y changes and internal
binding writes. Undo/redo discards pending automatic work. It waits for mouse release,
closed native transactions/task panels and idle TechDraw calculation. Geometry and
CAD work stay on the GUI thread; authorization HTTP requests use existing workers.
No network work occurs at startup. Automatic linking has a separate undo transaction.

Ordinary and projection-group views without perspective use the native projection
basis and source-shape centroid. Balloon origins are unscaled and unrotated; a model
space line through the origin follows the viewing direction. Distance to each placed
component shape detects solid interiors and edges within 0.25 mm paper tolerance.
This intentionally retains overlapping/occluded candidates rather than guessing depth.
There is no distant-nearest-component fallback. Source groups are traversed; pinned
external subassembly links remain direct engineering components. Fasteners use their
verified standard association. Unmapped hits or hits absent from the frozen Direct
BOM block assignment. Repeated occurrences and split entries stay separate candidates.

A unique hit and unique frozen entry link automatically. Multiple hits/entries require
a chooser that highlights candidates and restores prior selection. One compatible
Direct table is selected automatically; an existing compatible target is retained,
otherwise multiple tables require selection. Link BOM Balloon offers automatic retry
for a selected native balloon and retains explicit manual linking.

Working copy, lifecycle, edit permission, session, live owned lease and local evidence
are checked before changes; successful resolution is revalidated after choices.
Failed resolution displays ? with retained recovery metadata. Without authorization,
no automatic CAD mutation is allowed; log in and retry explicitly. Automatic geometry
changes never synchronize server BOMs, save, upload or check in.

Automatic bindings use JSON version 2 with version-1 BOM identity plus attachment
component name and frozen view/origin/shape evidence. Their tables use format 6;
manual links remain version 1 and formats 1–5 remain readable. Explicit table updates
preserve format 6 and validate automatic attachments. PDF preflight detects changed
geometry/arrow evidence even if the observer was unavailable. Older addons reject
format-6 edits; native expression/graphics still display offline. No backend/schema
change is required. Reopening does not adopt legacy balloons or refresh attachments.

Section/detail/broken/perspective views remain explicit manual workflows. Native
geometry attachment is not durable individual-instance tracking across arbitrary
remodeling. The current workflow belongs to the [drawing guide](../user/drawings.md).
