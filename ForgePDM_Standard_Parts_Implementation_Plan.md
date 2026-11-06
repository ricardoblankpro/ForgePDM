# ForgePDM — S parts and Fasteners integration

Status: implemented in addon 0.7.0 and backend migrations 10–11, 2026-11-05.
This is the final implementation sequence agreed from the original simplified
proposal. See [usage and limits](docs/standard-parts.md),
[ADR-010](docs/decisions/ADR-010-standard-parts-and-fasteners.md) and
[live evidence](docs/validation/standard-parts-freecad-2026-11-05.json).

## 1. S numbering and catalog access

Ordinary part Items gain an independent S series. Existing P/A defaults, numbers,
UUIDs, revisions, checkouts, lifecycle and memberships remain. Add S creation and
search filtering, metadata-only registration and explicit metadata check-in/release.
Migrate from the old schema without resetting counters or changing relationships.

## 2. Workbench discovery and matching

Keep Fasteners Workbench insertion tools. Discover its shared FSScrewObject
parameter contract across families. Normalize geometry and store immutable
purchasing specifications with explicit material/grade/finish, including unknowns.
Match only accessible catalog entries; require confirmation of details geometry
cannot determine. Protect concurrent duplicate registration within a project.

## 3. Upload and Check In association

Automatically run preflight before preparing a new saved snapshot. Reuse valid exact
revision associations. Group unresolved objects, present catalog candidates, or offer
prefilled S registration. Cancellation stops preparation; confirmed registrations
remain reusable. Geometry changes require reassociation; copied objects receive
new occurrence UUIDs. Save adapter/generator provenance in addon-owned properties.

Normal toolbar-created document-root fasteners and direct members of a single native
Assembly are direct engineering occurrences. Nested local groups remain unsupported.

## 4. Safe persistence and reviewed BOM

Persist occurrence evidence with the exact native dataset transaction, independently
of external CAD dependencies. Atomic check-in replay binds the same source bytes.
Support local attachments and narrowly specified external BaseObject subelements
through exact managed file/object pins and a versioned manifest profile. Verify
reconstruction and reject unresolved/null targets; preserve old link-only snapshots.

Combine linked and embedded direct occurrences in existing BOM selection/review.
Aggregate by exact revision, preserve manual-line review and subassembly boundaries,
and reject stale snapshots/checkout conflicts. Upload and Check In do not mutate BOMs.

## Acceptance and boundary

Automated tests cover migrations, concurrent numbering/registration, permissions,
metadata lifecycle, matching, evidence and replay, edit invalidation and mixed BOMs.
Live FreeCAD/HTTP evidence covers four fastener families, external/local managed
attachments, quantity eight, two occurrences of a purchased S model, check-in,
historical reconstruction, cancellation, copies/deletion, stale previews and nested
assembly boundaries. The adapter is general across the shared parameter contract;
not every standard or FreeCAD/Fasteners version has been individually validated.

Defer supplier equivalence, inventory, ERP, taxonomy, arrays, arbitrary proxies,
semantic topology remapping, automatic release and automatic revision adoption.
Existing Phase 5 legacy-write/revision-retry debt remains tracked separately.
