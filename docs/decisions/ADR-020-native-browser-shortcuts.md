# ADR-020 — Persistent native browser and local shortcuts

Status: implemented, 2026-11-12. User requested the remaining opening UX increments,
removal of the Name column and a future thumbnail plan. User explicitly keeps
component insertion in FreeCAD's native assembly tools for this increment.

## Interaction and ownership

The existing Open command shows one modeless, dockable browser for the signed-in
session. It stays open after retrieval, can float/hide, and the toolbar reuses the
same instance. Preserve the command ID and the existing nine-action toolbar.
Use one-click All Items, Recent Items, Favorites and My Checkouts tabs. Remove
only the visible Name column; names remain searchable, without changing metadata.
Revision/snapshot selectors and the configured workspace remain visible.

Favorites bookmark item identities and resolve current authorized metadata.
Recent Items store exact item/revision/dataset/file pins after successful opening
or successful reactivation of an already-open exact snapshot. They never silently
follow the latest revision/upload. A missing recorded snapshot disables opening
until the user explicitly chooses another snapshot. My Checkouts uses the existing
authenticated `/me/checkouts` API and exact lease revision; expired leases are
labelled. Merely opening never acquires or renews checkout.

Keep at most 100 favorites and 30 recent snapshots in the FreeCAD preferences
scoped by server/account. Persist IDs only, never labels, paths, credentials or
bearer tokens. Preferences are local to the FreeCAD profile, not shared with web
or other machines. Resolve IDs via authorized APIs every refresh; omit unavailable
records without deleting the local bookmark. Corrupt preferences fail closed and
are preserved for inspection. Users can remove favorites or clear recent history.

## Session, worker and document safety

Use the existing bounded asynchronous search engine and native configuration
retrieval. Invalidate stale query/source/revision responses immediately. Hide
cancels browser reads; pending requests drain responsively. Logout/account change
hides and clears the old panel before another session is displayed. Dispose only
after pending reads/opening settle. An old response cannot populate the new panel.
Do not initiate browsing/network work at addon startup.

Opening uses the existing single-operation task controller and its cancellation,
progress and errors. Disable the browser during opening. Recheck session identity
before opening/activating CAD following HTTP; retain dirty-document and exact-pin
guards. Store recents only after success; a preference-write failure must not
undo a successful CAD opening. Restoring shortcuts never writes server metadata.

## Bounds and deferred work

Use existing backend APIs with no schema/restart requirement. Local shortcut
resolution can issue one item/revision read per entry; larger lists load more
slowly. My Checkouts scans at most 1000 leases before filtering/paging and reports
that limit. A backend bulk/filter endpoint is a future performance improvement.
Closing/hiding cannot forcibly interrupt an already-blocked HTTP read; callbacks
are invalidated and the UI remains responsive while the request times out.

Native insertion, check-in, BOM synchronization and revision adoption remain
explicit separate actions. Thumbnails are documented in
[the future plan](../thumbnail-plan.md), not implemented in this increment.
