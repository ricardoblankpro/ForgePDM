# FreeCAD workflow

Use the ForgePDM Workbench to operate on managed documents. The server owns PDM
identity, permissions, revision pins and lifecycle. Display labels are not IDs.

## Browse and choose a workspace

**Open from ForgePDM…** opens a persistent dockable/floating browser. Search by
item number or description and filter P/A/S items. Select the intended revision
and exact native snapshot before opening. Current revision/newest uploaded native
snapshot are initial defaults, not substitutions for explicit historical choices.

- **All Items** searches the authorized catalog.
- **Recent Items** retains up to 30 exact successfully opened snapshots.
- **Favorites** retains up to 100 local item bookmarks and resolves current access.
- **My Checkouts** shows your server leases, including expired leases.

Shortcuts are scoped to the FreeCAD profile, server and account. Clear Recent
affects local history only. Unavailable records are omitted without deleting
bookmarks. Missing native CAD prevents opening that snapshot. Hiding/reopening
the browser preserves its controls; changing accounts clears protected content.

Use **Session → Set Workspace…** to configure a local root per server/account.
Managed working copies live under `working/<uuid>/model.FCStd`; retrieved
configurations live under `configurations/<uuid>`. The `.forgepdm` directory holds
verified caches, locks and ledgers. Keep the whole workspace together and do not
edit its ledgers manually. Configuration folders accumulate; cleanup is explicit.
Opening the same exact snapshot activates an existing document and preserves its
unsaved edits. A different snapshot opens separately.

## Snapshot previews

The browser shows an isometric preview of the selected **Uploaded CAD** snapshot.
Changing revision or upload changes the image; an older selection never borrows
the newest upload's preview. Missing or unavailable previews show a placeholder
and do not prevent opening CAD. Changing accounts clears protected images.

New Upload and Check In operations prepare a 384px isometric PNG after saving the
model. Generation preserves your camera, selection, visibility, animation setting
and saved file bytes. A dirty linked component prevents a potentially misleading
preview. Automatic capture currently limits each model/dependency file to 256 MiB
and uses an existing 3D view. A document without a usable 3D view gets a placeholder;
this increment does not render drawing sheets separately.

Preview failure does not undo a successful CAD upload/check-in. If a check-in
preview remains pending, retry **Check In** to recover the same saved image while
that operation remains current. Newer local edits are never included in that retry.
Normal Upload reports optional preview failure but has no separate repair command.
Previously uploaded files are not automatically opened, saved or backfilled.
Use backend 0.1.2 or later for the thumbnail API; CAD workflows remain compatible
when an older server cannot accept a preview.

## Create, edit and publish CAD

1. Save the FreeCAD document. **Create / Upload Current Document** registers a new
   P/A item in an editable project and prepares a managed working copy. An admin
   may create a projectless item. New items start at Working revision A with an
   eight-hour checkout owned by their creator.
2. Upload managed components before their parent. The parent captures exact
   revision/dataset/file/object references; save/upload component changes first.
3. Use **Check Out / Renew** on an existing Working revision to obtain or renew
   your lease and prepare an editable working copy. Retrieved snapshots remain
   read-only until a supported working-copy operation prepares another file.
4. Edit and save. **Upload** publishes a native snapshot and keeps the checkout.
   **Check In** saves and atomically publishes the native file, dependency
   manifest and evidence, then releases the checkout. It does not prompt for a
   change note; an omitted note preserves the revision note.
5. **Release** makes a checked-in Working revision immutable. An assembly's
   direct components must already be Released. Upload/check-in does not
   synchronize the engineering BOM; use [BOM review](bom.md) separately.

A failed response may leave a durable operation journal. Retry the command to
recover the original result before starting a new intent. Newer unsaved changes
are preserved and are not silently included in an old retry. Keep journals with
workspace backups; see [recovery](../operations/server.md#recovery).

## Revise or update a component

**Create Next Revision** requires a change note and opens a separate Working
revision. The original document and existing assembly links retain their exact
revision/snapshot pins. New revisions copy their descriptions and stored BOM.

**Update from Server** reviews a newer uploaded snapshot of the same revision
and opens a separate configuration. It does not adopt a newer revision or discard
local edits. **Manage Component…** offers three distinct reviewed actions:
update the same-revision snapshot, adopt a newer revision, or replace the item.
Different-item replacement requires explicit object mapping. Inspect geometry and
joints afterward, then save/upload and review the engineering BOM separately.
A newer-revision notice never changes a pin automatically.

## Assembly support and tree display

Supported managed graphs include whole-object external `App::Link` references
and the bounded native `Assembly::AssemblyLink` adapter. Repeated occurrences and
native subassemblies retain their own pins. Standard joints are constraints and
do not count as BOM components. Arrays, arbitrary proxies, general subelement
links and cross-document expressions require separate adapters. Fasteners has a
specific association adapter; see [components](components.md).

Tree labels use `ITEM-REVISION|OCCURRENCE`, such as `P000001-B|2`. Occurrence
numbers are scoped to the immediate parent and exact component revision, survive
reordering and are not reused after deletion. They are not quantities or BOM
positions. **Refresh ForgePDM Tree Labels** requires an owned Working checkout.
The tree also projects description and PDM status. Status notices are refreshed
on demand and do not replace server authorization. Raw FreeCAD File → Open can
use a filename as the document heading; managed opening reapplies PDM identity.
