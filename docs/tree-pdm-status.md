# PDM status in the FreeCAD tree

Current tree integration also provides a read-only **Description** column next
to PDM status: P rows show the pinned M text and A rows show their free-text
description, including exact linked revisions. It preserves native labels and
Label2 data and can display pending local descriptions. See
[material descriptions](material-management.md). Status refresh remains a read-only
presentation operation; explicit assignment/recompute may update engineering mass
metadata only under the owned editing workflow.

## Implementation plan

1. Add a read-only, bounded batch API for exact revision status. In one metadata
   read transaction, authorize every requested revision, return lifecycle, active
   checkout owner/display name/expiry, newest non-obsolete revision and latest
   native dataset/file IDs/hash/timestamp. Unavailable and missing revisions have
   identical responses. No user directory, storage paths or credentials exposed.
2. Capture managed document/link identities on the GUI thread. Resolve local
   snapshot pins from workspace ledgers in a worker; compare per occurrence, not
   per item. Unknown or unuploaded pins must not be marked current.
3. Add a temporary PDM column to native Gui::TreeWidget instances. Preserve all
   native columns/icons/error colors and CAD labels/properties. Show independent
   colored badges and text, with an escaped detail tooltip and refresh timestamp.
   Resolve objects by internal name within a uniquely identified document/context;
   ambiguous document roots remain unknown rather than guessed from display labels.
4. Add Refresh PDM Status. After explicit activation, refresh in the background
   at 60-second intervals and after completed PDM commands; no startup network.
   Use asynchronous workers, coalesce requests, defer during CAD jobs/modals,
   reject results after login/logout/document identity changes, and mark failed or
   old results stale. Clear private cached statuses on logout/account switch.
5. Test permissions/expiry/pins and pure status rules, packaging, real Qt tree
   decoration, lifecycle/checkout/new-revision/new-snapshot combinations, offline
   handling and zero changes to CAD labels, dirty state, saved bytes or selection.

## FreeCAD adaptation

Prototype tested on FreeCAD 1.1.4 / Qt 6.8.3. Native tree uses three columns;
column 2 stores object internal names. Qt item EditRole on columns 0/1 renames
CAD labels, so this implementation uses only its own column (3) and a non-editing
delegate. Native providers are never replaced. Source inspected for compatibility:
[FreeCAD Tree.cpp at the tested revision](https://github.com/FreeCAD/FreeCAD/blob/4fd3bf320d9566a27e60069fc8387448aaa3a094/src/Gui/Tree.cpp).
No third-party source is copied. This is a bounded adapter, not a stable upstream
Python tree-decoration API; other FreeCAD versions require acceptance testing.

## Usage — addon 0.6.4

Sign in, then choose **ForgePDM → Refresh PDM Status** once. The PDM column appears
beside labels; it refreshes every 60 seconds and after PDM commands complete.
Hover a status for full owner/expiry, lifecycle, exact local/server snapshot IDs
and last successful server check. Refresh is read-only, including on released
documents or without your own checkout. It never changes links or adopts revisions.

| Badge | Meaning |
| --- | --- |
| Blue / You | You hold the active revision checkout |
| Orange / user name | Another user holds the active revision checkout |
| Green / Released | This exact revision is released |
| Purple / Rev … available | A newer non-obsolete revision exists |
| Teal / Snapshot update | This occurrence pins an older upload of the same revision |
| Brown-orange / Local edits | Unsaved or saved-but-unuploaded local changes |
| Gray / Snapshot unknown | No verified uploaded pin is available for comparison |
| Gray / Ambiguous copy | Several open documents cannot be distinguished safely in the native tree |
| Gray / Stale status | Request failed, refresh is pending, or last check is over 90 seconds old |

All badges can coexist. A released revision can have both revision and snapshot
updates. Repeated occurrences compare their own dataset/file IDs independently.
Colors supplement text and tooltips. Badge dots remain visible when text is elided;
widen the tree dock or adjust columns for more text. Native icon/error/visibility
display remains intact. The adapter temporarily uses an interactive label-column
width and restores its previous mode/width when removing the status column.

Log out to clear private cached information and remove the column. With the feature
already activated, signing in again resumes refresh for the new account. No network
requests occur at addon startup, and no tokens/status data are saved in CAD files.
File hashes are checked in a worker and cached by file-stat signature; unchanged
files are not repeatedly rehashed. Large first-time workspaces may take longer.

Use **Update Selected Components from Server…** for snapshot updates, and
**Replace with New Revision…** for revision changes. Indicators never grant editing
permission; each engineering command independently checks current server rules.

## API and operational boundaries

`POST /api/v1/status/revisions` accepts 1–200 UUIDs in `revision_ids`. Addon requests
larger sets in chunks, deduplicating shared revisions. Each batch is read in one
metadata transaction and returns `Cache-Control: no-store`. No schema migration.
Missing and inaccessible IDs have identical `available: false` results. Checkout
display names are exposed only for readable revisions, not as a user directory.
Expired leases do not appear as active checkouts. Restart an older backend to load
the additive route; old servers display a stale status and an upgrade explanation.

FreeCAD does not expose document identity directly on its native Python tree
items. The adapter matches a document label plus scoped internal object names
only when there is a unique document candidate. If several indistinguishable
copies are open, those document roots are marked unknown instead of guessed.
Their occurrences in a uniquely identified parent assembly can still show correct
per-snapshot status. Native AssemblyLink generated children resolve through their
link contexts. Unmanaged, foreign-server and unsupported references remain unknown.
Another extension owning additional native tree columns prevents this adapter from
attaching; coexistence needs a dedicated integration rather than overwriting it.
If another extension adds a column later, logout still scrubs private status cells
and preserves that extension's column.

Polling gives bounded-delay status, not live locking notifications. During CAD
commands and modal dialogs it defers refresh. Failed requests mark cached values
stale; late replies from a previous session are discarded. The feature does not
modify engineering rules, auto-save, check out items or synchronize stored BOMs.

Validation: 103 backend tests and 260 addon tests passed, plus isolated live Qt/HTTP
acceptance checks for multiple users, mixed snapshot pins, simultaneous badges,
offline recovery, logout/account-switch races, command deferral and unchanged CAD
labels/properties/dirty flags/files/selection. Native screenshot inspected locally.
Evidence: [live report](validation/freecad-tree-status-2026-11-03.json).
