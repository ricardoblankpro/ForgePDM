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

## Tree descriptions

The native tree's **Description** column follows the description language selected
in the ForgePDM browser, as do subsequent assembly BOM reports and drawing-table
generation. Approved translations appear where available; otherwise the original
description is shown. **Original descriptions** always shows original text.

Embedded Fasteners and links to them show the description of their exact associated
S revision. They keep their containing document's checkout/status context. If a
Fastener has changed size or lacks a usable catalog association, the tree shows
its local parameters or label until the association is reviewed through the normal
Upload/Check In workflow. It never borrows the assembly description.

Hover over any populated **Description** cell to read its full text without widening
the column. These tree presentations do not modify labels, `Label2`, description
metadata, geometry, saved files or frozen drawing tables. An explicit unsaved source
description remains visible until saved/reconciled; it never acquires a translation
of different text. Language changes refresh the tree asynchronously.

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

ForgePDM saves refresh external link paths to their currently loaded components,
including working copies moved to another folder. Exact component identities and
placements are retained. If an upload reports that a CAD reference changed, keep
the assembly and its components open and retry with addon 0.24.4 or later. The
saved snapshot must still pass reference validation; unresolved components or
genuine target changes require inspection. A failed upload can leave an existing
item or checkout, so continue with that item rather than creating a duplicate.

## Managed editing, component updates and cancellation

**Open for Editing** opens a separate managed working document and acquires or
renews your checkout. The original saved configuration and other assemblies keep
their references. Checkout retains the source snapshot baseline, so no preliminary
parent upload is needed before component updates. The editing action offers newer
uploads of the same component revisions; you can keep the saved configuration.
**Open** continues to retrieve the selected saved configuration without checkout.

Edit a child and save it locally. In the parent, select its occurrence and choose
**Manage Component… → Update saved local changes of the same revision**. Choose
the saved working copy if several exist. The child needs your live checkout.
The occurrence chooser selects all matching direct occurrences of that item/revision
by default; deselect any you want to retain before confirming the review. The child
need not be uploaded first. Unsaved source changes are excluded: save them before review.
Adoption freezes a separate local generation, so further child editing does not
change the parent until another update. These generations survive restart.

Use **Update Selected Components from Server…** to adopt a newer uploaded snapshot
of the same revision. **Create Next Revision** creates a separate revision;
**Manage Component…** also offers explicit newer-revision adoption and item
replacement. Different-item replacement retains explicit object mapping.

Deleted or added source fasteners are structure changes. New representations
record member identities independently of live links. If an older assembly reports
missing members, use **Reconcile Component Representation…**. It verifies the
saved uploaded source and recorded occurrence identity, then rebuilds the members
without recreating the occurrences. Missing source identity, ambiguous legacy
records or unresolved joints stop recovery. A joint attached to deleted geometry
must be repaired or removed explicitly; unrelated joints and placements remain.

**Upload Assembly Graph…** and **Check In Assembly Graph…** review the active
assembly and its dependencies. Changed editable documents are saved child-first;
missing checkouts require explicit acquisition. Upload retains checkouts; Check In
releases each published document's checkout. Frozen local generations are published
before their parents and receive real server pins. Existing editing documents are
retained, including newer changes made after publication was prepared. Preview
capture remains optional. Review engineering BOM synchronization separately.

A graph operation freezes its original saved inputs before publishing. Retry the
same graph command after an interruption to recover its original operation.
Completed children remain published if a later document fails; this is not one
server transaction across the whole assembly. Resolve multiple distinct saved
configurations of the same revision before coordinated publication.

**Cancel Check Out…**, available from the document menu and browser, abandons
unpublished local changes and releases your exact checkout. Select the working
copy when several exist. The review names affected open parents and retains
recovery copies of saved and unsaved documents under the workspace's
`.forgepdm/recovery/`. Affected parents return to the reviewed uploaded snapshot;
unrelated edits remain. Incompatible joints or missing parent edit rights stop
restoration. Interrupted publication must be recovered first. For a revision with
no uploaded snapshot, cancellation preserves its local recovery copy and leaves
the server item/revision intact.

Cancellation never removes uploaded history. Changes already uploaded remain
published; reverting them is a separate engineering action. Keep recovery bundles
and graph-operation snapshots with workspace backups; automatic pruning is not
provided. See [server recovery](../operations/server.md#recovery).

## Insert components from the browser

Activate the destination assembly, then choose a P or A item, revision and uploaded
snapshot in the ForgePDM browser and click **Insert into Assembly**. The destination
must be a managed Working copy with your live checkout. Parts with several root
objects prompt for the object to insert.

Subassemblies insert as rigid units including supported Fasteners objects outside
the source Assembly container. Source fasteners and their attachments stay where
they are. The selected occurrence starts at the destination origin; position it
or add native Assembly joints. Each click inserts one occurrence, undoable as one
transaction. Generated representation objects are implementation details; edit the
occurrence rather than its member links. Use addon 0.27.0 or later for version-1 representations. Files updated to version 2 require addon 0.28.0 or later.

Insertion uses the chosen uploaded snapshot, including its pinned dependencies.
Unsaved source edits are not inserted. Save/upload the destination explicitly and
review its engineering BOM separately; the parent counts one subassembly occurrence,
while its fasteners remain in the subassembly BOM.

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
