# ForgePDM Browser — addon 0.17.0

Use **ForgePDM → Session → Set Workspace…** once after login. The folder is
remembered per server/account. The browser also offers **Change…**; if no valid
folder is configured it asks once when opening. Existing managed documents keep
their own workspace for editing/upload. Missing/unwritable folders, linked
metadata and a workspace belonging to another server are rejected. A previous
global folder is adopted only for the matching saved server/username.

## Browse alongside CAD

**Open from ForgePDM…** shows a modeless, dockable panel. Keep it beside the model
or float it. Hide closes no CAD documents; the toolbar shows the same panel again.
The panel remains available after opening. No browser requests run at startup.

Type a number, name or description; results update after a short pause. Names
remain searchable but the **Name column is removed**. Results show Item,
Description, Revision and Lifecycle. Filter P parts, A assemblies or S purchased
parts. Arrow-down moves focus to results; Enter or double-click opens. Input has
a clear button. Result paging and revision/snapshot history stay in the panel.

- **All Items:** authorized catalog; current revision/newest native upload are
  visible initial defaults.
- **Recent:** the exact revision and snapshot previously opened, newest
  opening first. Different snapshots of the same item can appear separately.
  A missing recorded upload never silently becomes the latest upload: choose an
  alternative explicitly. Clear Recent removes local history only.
- **Favorites:** star/unstar the selected item. A favorite resolves its current
  revision when selected, rather than pinning an old revision.
- **My Checkouts:** your server-reported active and expired leases. Expired
  checkout rows are labelled; opening does not acquire or renew a lease.

Recent history and favorites persist locally in the FreeCAD profile, separated
by server/account. They do not synchronize to the web or other computers. Store
limits are 30 recent snapshots and 100 favorites. IDs are checked against current
server permissions on refresh. An unavailable record is omitted while its local
bookmark remains. Corrupt shortcut data is preserved and reported, not reset.

## Exact files and local edits

Revision and Uploaded CAD selectors remain visible. Load older revisions in
place; a revision without native CAD cannot open. Dates use local time; a tooltip
shows the content hash. Search results reflect metadata as loaded, not a live
revision subscription. Selections pin exact revision/dataset/file IDs.

An already-open exact snapshot is activated after access revalidation, retaining
all edits. Another snapshot opens separately. Retrieval preserves the selected
assembly's recorded component manifests. Success uses the status bar. Opening
never acquires checkout, publishes CAD, synchronizes BOMs or adopts new revisions.
Component insertion stays in FreeCAD's native assembly tools.

HTTP runs on bounded workers, document/UI work on the main thread. Late responses
cannot replace newer searches or populate another account's panel. Session changes
hide and clear protected UI. The panel is disabled during opening; CAD progress,
cancellation, errors and dirty-document protection use the existing task flow.

## Limits and future work

No backend/schema change is required. Larger shortcut lists may load more slowly
because the client resolves authorized metadata per entry. My Checkouts scans up
to 1000 leases and reports that cap. Pending HTTP reads can take until timeout to
drain while the UI stays responsive. Workspaces accumulate configurations; there
is no automatic cleanup.

Shared thumbnails for this panel and the web GUI are **planned, not generated**.
See [the future thumbnail plan](thumbnail-plan.md) and ADR-020 for design details.
