# ADR-029 — Explicit balloon links to frozen drawing BOM entries

Status: accepted, 2026-11-19. Extends ADR-021/022/028. The owner selected the
existing **BOM Position** for balloon text; sorting never renumbers the EBOM.

The first increment adopts an existing native `TechDraw::DrawViewBalloon` into
a frozen **Direct** table on the same page/document. The user explicitly selects
the table and entry by position, item, exact revision and description. Native
leader geometry and style are preserved. Neither a projected geometry click nor
an existing literal number proves the engineering identity.

The balloon stores a native `App::PropertyLink` to its table, versioned JSON
identity, displayed position and status. A native expression binds `Text` to
its string position property. No Python proxy, observer, external file or server
is needed for offline display/save/reopen. This reuses the
[upstream native balloon](https://github.com/FreeCAD/FreeCAD/blob/4fd3bf320d9566a27e60069fc8387448aaa3a094/src/Mod/TechDraw/App/DrawViewBalloon.cpp)
without copying its source (LGPL-2.0-or-later).

Identity freezes the root revision, exact component revision, stored position,
row key and the sorted set of keys for all direct entries of that revision.
Visual row indexes, localized descriptions, quantities, report tokens and
recreated database line UUIDs are not identities. Repeated entries at distinct
positions are supported. Their occurrence set must remain unchanged: split,
merge, renumber, replacement, root/view changes or missing/ambiguous rows require
explicit relinking. A conservative policy avoids guessing continuity where the
backend has no durable occurrence identity. Indistinguishable replacements of
the same revision at the same positions cannot establish physical-instance
continuity; geometry attachment remains a separate native concern.

Explicit table updates refresh linked balloon properties in the **same undo
transaction** as the SVG and frozen report. Invalid links display `?`, retain
their saved identity and receive an Unresolved status. Preview and completion
identify affected balloons. Unresolved status is sticky until explicit relinking;
a subsequently returning row cannot silently restore a target. Other tables and
unadopted native balloons are untouched. Table deletion leaves a detectable
orphan; reopen/recompute never rewrites saved data or fetches a report.

Adoption upgrades that table to **PDMTableData format 5**; subsequent edits keep
format 5, including after balloons are removed. Older addons reject its updates
instead of leaving balloons stale. Formats 1–4 remain readable and unchanged
until explicit actions. Embedded SVG and native balloon graphics remain viewable
without ForgePDM. No backend/API/schema migration is needed.

Linking requires the managed assembly Working copy, edit permission and owned
live checkout, with document/session/lease and reviewed local-data revalidation
after the dialog. It links the frozen table, without fetching a competing report
or synchronizing CAD/EBOM. It never saves, uploads or checks in automatically.

ForgePDM PDF export checks adopted balloons on selected pages of the verified
uploaded snapshot. Invalid/orphan links, changed expressions or inconsistent text
block new rendering with an explicit correction/upload instruction. Valid older
literal balloons remain allowed. Native TechDraw export outside ForgePDM is not
gated; existing published PDFs and durable publication retries are unchanged.
This is a frozen-link integrity gate, not a current-server stale-BOM gate.

Nested/flattened entry semantics, automatic recognition/placement, physical
leader reattachment and durable backend occurrence identities remain later work.
Current workflow is owned by [the drawing guide](../user/drawings.md).
