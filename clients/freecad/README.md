# ForgePDM FreeCAD Workbench

This is a thin FreeCAD client for the ForgePDM HTTP API. It keeps authentication and PDM rules on the backend; the Workbench only saves local documents, calls API operations, and adds a hidden `ForgePDM_Metadata` object to associate a FreeCAD document with its item and revision IDs.

## Install

The addon uses FreeCAD's modern `freecad.forgepdm` namespace. The declared
initial target is FreeCAD 1.0+ with embedded Python 3.11+. The addon has been
exercised on Linux with FreeCAD 1.1.4, Python 3.11.14 and Qt 6.8.3; other runtime
combinations remain unverified. No ForgePDM backend package, pip installation or network access
is required to load the Workbench. A reachable server is needed for its commands.

Build an addon-only archive from the repository root:

```sh
uv run --project clients/freecad --extra dev python clients/freecad/tools/addon.py check
uv run --project clients/freecad --extra dev python clients/freecad/tools/addon.py build
```

The output is `clients/freecad/dist/ForgePDM-0.11.0.zip`. Create a `ForgePDM`
directory inside your FreeCAD user `Mod` directory and extract the archive there.
The resulting layout must be `Mod/ForgePDM/package.xml` and
`Mod/ForgePDM/freecad/forgepdm/init_gui.py`. Do not extract into an extra nested
`ForgePDM` directory. You can find the user directory in FreeCAD's console with
`App.getUserAppDataDir()`; use its `Mod` subdirectory.

For local development, copying or linking the entire `clients/freecad` directory
as `Mod/ForgePDM` also works. **Remove the previous installed `Mod/ForgePDM`
directory first** (back up any user files stored there). Do not overlay it: stale
`InitGui.py` and the new entry point can load competing clients. CAD working files
belong outside the addon installation. Restart FreeCAD after installation.

This ZIP is an independent manual-install preview. The monorepo URL is not yet
an Addon Manager distribution source, and no Addon Index entry is published.
Code/asset licensing and maintainer contact approval remain required before
public release. See [validation](Documentation/validation.md) for automated
checks and the required real FreeCAD acceptance checklist.

Select **View → Workbench → ForgePDM**. The backend must be running and reachable from FreeCAD. The default login URL is `http://127.0.0.1:8000`; use the URL of your ForgePDM host for a separate server.

## Workflows

1. **Log In** opens a connection form with server URL, username, password and request timeout. URL, username and timeout are remembered; passwords and bearer tokens are not saved. Expired/revoked sessions prompt you to log in again.
2. **Create / Upload Current Document** lets you choose an authorized project by number/name for a new Item, creates a managed working copy, attaches hidden item/revision metadata, and uploads a verified `native_cad` snapshot with its exact component references. Only editable projects are offered; administrators may choose a projectless Item.
3. **Acquire / Renew Checkout**, **Check In Current Revision**, and **Release Current Revision** manage the current revision. Check-in uploads the saved native file first and then releases the checkout without prompting for a change note. The intended workflow is check-in before release; release prerequisites remain enforced by the existing backend.
4. **Create Next Revision** creates the next Working revision in a separate managed file, updates the local metadata and uploads its native snapshot, preserving the previous revision file.
5. **Download Item / Assembly** searches by item number, name or description (blank to browse), offers pages of matching items, then lets you select a revision, including historical revisions. Select an exact native snapshot if several exist. It retrieves the pinned CAD reference graph into a new configuration and verifies external links before completion. Missing/inaccessible components stop retrieval before opening the assembly.
6. **Show ForgePDM BOM** displays the current revision's recursive BOM. Choose
   **Synchronize from CAD…** on a saved/uploaded Working assembly with your active
   checkout. Select engineering occurrences, review exact revisions, quantities,
   source occurrences and quantity changes, then explicitly approve replacement.
   This replaces all current lines, including manual lines. An empty proposal
   explicitly clears the BOM. Canceling either dialog preserves the BOM.
7. **Refresh ForgePDM Tree Labels** updates an owned Working assembly to show
   `P000001-B|1` on its managed component links. Save/upload persists the changes.
   The command also verifies the checkout used for subsequent automatic insertion
   updates. Acquire a checkout and managed working copy first.

The API upload accepts one file per Dataset. Project authorization and all PDM
rules remain on the server. Downloads require access to every referenced
component revision. Internal UUIDs are carried by the client; you do not need
to enter them when selecting projects, items or revisions.

## Tree labels and occurrences

Tree links display item number, pinned revision and occurrence, for example
`P000001-B|1`, `P000001-B|2` or `A000003-C|1`. Numbering restarts for each exact
item/revision inside each parent assembly; a subassembly numbers its own children.
The suffix is an occurrence index, not a quantity or BOM position. Removing a
link leaves a gap. Reordering leaves numbers unchanged; copied links receive
fresh UUIDs and the next index. Item/Revision UUIDs and internal object Names
remain the identities used by ForgePDM.

Labels and allocation history are stored in CAD properties and applied during
upload and verified retrieval. After checkout or explicit refresh has verified
local editing permission, inserted links update automatically after the native
operation completes. The observer waits while commands/dialogs are active and
does no startup networking. Check-in/release disable its cached permission.
Unmanaged, foreign, array and subelement links keep their existing labels.

The document heading displays `ITEM-REVISION` through managed workflows. Raw
FreeCAD File > Open may use the filename for that heading; stored link labels
and numbers remain intact. Use managed retrieval or Refresh Tree Labels to
reapply the heading. Original labels remain available in ForgePDM properties.

## Managed workspace

Choose a workspace folder when first uploading or retrieving. Originals, including
bundled read-only examples, are preserved. New working copies live in
`working/<uuid>/model.FCStd`; downloaded graphs live in `configurations/<uuid>`.
The hidden `.forgepdm` directory holds server identity, locks, staging and a
SHA-256 verified cache. Keep the complete workspace together when relocating it.
Do not edit its ledgers or cache. Retrieval always creates a new configuration.

Upload each linked component first, from a managed workspace on the same server.
Save and upload component changes before uploading the parent. This version
supports whole-object external `App::Link` references, including nested and
repeated occurrences. It rejects unsupported subelement references and
cross-document expressions; other assembly adapters remain unverified.

Downloaded files are locally read-only. Use Acquire / Renew Checkout to create
an editable working copy of a Working revision, or Create Next Revision for a
Released revision. PDM edit permissions and lifecycle remain server-enforced.
An old assembly pins its original component revision/dataset/file, even after
newer component revisions are created. Engineering BOM synchronization is a
separate reviewed operation. CAD dependencies may include references excluded
from the engineering BOM; reconstruction always follows the pinned CAD manifest.
The retrieval ledger records revision-set differences without treating them as
CAD corruption. An empty BOM is not proof of consistency.

BOM extraction supports whole-object external links, internal links resolving to
those targets, and plain groups/parts as organizational containers. Every selected
link contributes one unit; external subassemblies count as one direct component.
Unselected links and local geometry do not enter the proposal. Arrays, subelements,
internal links to local geometry/groups, external link-to-link targets and custom
assembly proxies require a dedicated adapter and are rejected. Hidden links are
still candidates: use explicit selection to exclude templates or construction aids.
Save/upload changed components and then their parent before synchronizing.

The built-in Assembly workbench is supported for one `Assembly::AssemblyObject`
with direct whole-object `App::Link` components. Its standard joint group and
`JointObject.Joint`/`GroundedJoint` objects constrain geometry and do not contribute
BOM quantities. Nested local native assemblies, indirect component groups,
unrecognized assembly objects and custom joint proxies are rejected explicitly.
Use linked external subassemblies for nested product structure. This does not
certify all built-in Assembly features or third-party assembly workbenches.

## Current limits

Network requests and file transfers run in a worker with progress reporting.
Other ForgePDM commands are disabled while a workflow is active, while FreeCAD's
event loop remains responsive. Toolbar and menu actions refresh automatically
when the workflow finishes, including cancellation and failures.
Cancellation stops subsequent steps and removes
partial downloads; a blocked request may need to reach its timeout first.
Short finalization requests cannot be canceled. Cancellation never undoes a
server commit, and failed/uncertain mutations are never retried automatically.
Check the revision/server state before repeating a failed upload or check-in.

CAD save/recompute still runs on the GUI thread. Native ZIP inspection and
path rewriting occur in the worker before opening files. Exact byte hashes are
verified for cache hits as well as downloads. Existing local files are never
silently replaced. A failed retrieval can be retried; it uses a new configuration
and verified cached bytes. Inspect an unreadable/unknown workspace lock instead
of deleting it while another operation may be running.

Downloaded components are saved cleanly after reconstruction. BOM synchronization
still rejects genuine unsaved edits and identifies the affected item/revision.
After upgrading from 0.4.2, retrieve/reopen assemblies through ForgePDM once to
replace modification flags left in previously opened documents. Re-uploading an
unchanged downloaded component is not required to clear this old loader issue.

Native Check In publishes CAD bytes, pinned manifests and checkout release in
one fenced, replayable operation. Separate Upload/manifest operations still exist;
inspect server state after interrupted legacy writes. Further mutation idempotency
work remains. Only
native CAD files are transferred automatically, and the verified-cache download
publication requires filesystem hard-link support. Local read-only protection
is advisory. Third-party proxies, external textures and other CAD adapters are
not certified. Windows, macOS and network shares remain unverified.

Current addon **0.11.0** requires the updated backend through **migration 16**,
including descriptions (14), physical material/mass evidence (15), and supplier
reference mass (16). Earlier manifests, BOM snapshot and check-in APIs remain
required. Physical material/mass behavior has been validated on FreeCAD 1.1.4.
Back up the database and immutable files before updating/restarting
the server. The backend still runs separately from FreeCAD. Restart FreeCAD after
updating the addon. See [Phase 4 validation](../../docs/freecad-addon-phase4.md).

## Development resources

- [Connectivity decision](../../docs/decisions/ADR-003-freecad-connectivity.md)
- [Packaging decision](../../docs/decisions/ADR-002-freecad-addon-packaging.md)
- [Schema provenance and namespace adaptation](tools/vendor/README.md)
- [Official modern addon layout](https://freecad.github.io/Addon-Academy/Topics/Structuring/)

The original SVG icon is resolved relative to the installed module, and all
commands expose it in their resources. Menu labels/tooltips use FreeCAD's Qt
translation hooks. `resources/translations/ForgePDM_en.ts` is an English source
catalog; no reviewed translated catalogs or compiled `.qm` files are supplied.
After adding reviewed translations, compile them with Qt's `lrelease` and place
`ForgePDM_<locale>.qm` beside the `.ts` files before building. The build includes
both formats. Do not install another Qt binding into FreeCAD.

### Creating revisions without changing existing assemblies

Create Next Revision opens the new revision in a **separate document** and makes
it active. Existing assemblies keep linking the old document and its exact
revision. Edit the new active document to develop the new revision. The source
must be saved, clean and the item's latest Released revision.

Show BOM keeps displaying each pinned component revision and adds
`[Newer revision available: B]` when a later revision exists. This is informational;
it does not replace components or synchronize the engineering BOM automatically.

### Replace a component with a newer revision

1. Activate the clean, saved assembly working copy and hold its checkout. A
   Released assembly needs its own next revision before changing components.
2. Select one or more direct occurrences of the same item/revision in the tree,
   then use **ForgePDM → Replace with New Revision…**. Without a selection, choose
   the component in the dialog. Generated children inside a native subassembly
   must be changed from that subassembly's own working document.
3. Check the occurrences to replace, choose the newer revision and its uploaded
   native snapshot, then approve the replacement preview.
4. Inspect geometry and joints. Save/upload the assembly, then use Show BOM →
   Synchronize from CAD to review and persist its engineering BOM change.

The command keeps the existing occurrence objects, placements and UUIDs. Only
selected occurrences change; other instances can retain their earlier revision.
Source revision documents remain unchanged. Replacement leaves local unsaved
changes and can be undone in FreeCAD; it does not save, upload or write a BOM.

The new revision must contain compatible whole-object targets with the same
internal object names/types. Detected invalid geometry references or changed
joint references cause transaction rollback. Native subassembly replacements
that invalidate joints to generated children need manual mapping. Equal face
names do not establish semantic geometric equivalence: inspect the result before
saving. No assembly solver or automatic face/joint remapping is added.

### Replace with a different part or assembly

Use **ForgePDM → Replace Component…** to search by item number or name, choose
an exact revision and uploaded native snapshot, and map the source object to a
replacement Body, Part, Assembly or shape. Select the direct occurrences first,
or choose the source component in the dialog. Repeated occurrences of the same
source object share an explicit mapping; you can replace only some occurrences.
The final preview identifies the new item, revision and object mapping.

The parent must be a clean saved Working assembly with an owned checkout.
Item labels change to the replacement identity while occurrence UUIDs and
placements remain stable. Saving/uploading and BOM synchronization remain separate.
Replace with New Revision continues to offer only newer revisions of the same item.

Native subassembly links require a native Assembly target; converting those links
to parts or guessing new joint mappings is not supported. If an unselected internal
link would follow a selected occurrence, select its dependent occurrences too or
replace the dependent link independently. Invalid mappings and detected joint
errors are rejected or rolled back. Inspect geometry and joints before saving.

### Publish Drawing PDFs (0.6.6)

With your clean, uploaded managed document active and your own Working checkout,
choose **ForgePDM → Publish Drawing PDFs…**, select pages and review the source.
Open the revision's **Drawings** tab in the web GUI to preview/download the PDFs.
The command exports verified copies and preserves your open documents and lease.
After a connection failure, invoke the command again to recover the same PDFs.
Later native uploads/check-ins can make this publication historical; republish
explicitly when needed. See [workflow and limitations](../../docs/drawing-pdfs.md).

### Embedded TechDraw pages (0.6.5)

Native part/assembly uploads and check-ins now support TechDraw pages with valid
embedded self-contained SVG templates. Pages, editable title fields, dimensions
and notes stay in the model's exact native snapshot. Retrieval does not require
the original template path. TechDraw objects do not count as BOM components.
Other external assets remain unsupported; embed template logos as PNG/JPEG data
images. See [supported scope and validation](../../docs/techdraw-support.md).

### Visual PDM status (0.6.4)

Choose **Refresh PDM Status** after signing in to add the PDM column beside tree
labels. Colored badges show your/another user's checkout, released state, newer
revisions and newer same-revision snapshots. Hover for the owner's name/expiry,
exact pins and refresh time. It refreshes every 60 seconds and after PDM commands;
offline/stale values are explicit. Logout clears the column and private cache.
No CAD document changes or automatic component updates occur. See
[status legend, operation and limitations](../../docs/tree-pdm-status.md).

### Update selected assembly components (0.6.3)

Acquire the parent assembly's checkout and save/upload it. Select direct
occurrences of one component item/revision, then choose **Update Selected
Components from Server…**. Review the occurrence checklist and exact latest
snapshot. Selected occurrences adopt that snapshot of the same revision; other
occurrences stay pinned. Inspect geometry and joints, then check in the parent.
No automatic save, upload or BOM write occurs. See
[workflow and limitations](../../docs/update-from-server.md).

### Update from Server (0.6.2)

Choose **Update from Server…** on a clean managed document to check for other
users' uploads on the same revision. Review the timestamp/hash and open the updated
copy. The original stays open and all existing assembly links remain pinned.
Saved but unuploaded edits and pending check-in recovery block refresh. Newer
revisions are reported for explicit replacement. See
[workflow and limitations](../../docs/update-from-server.md).

### Reliable native check-in (0.6.1)

Check In uses one atomic operation for parts and supported assemblies, including
pinned external CAD references. Update/restart the backend together with this
addon. Servers without the explicit atomic-manifest route reject assembly uploads;
there is no downgrade to the earlier multi-request check-in. Separate Create /
Upload operations still use the legacy workflow.

If the connection fails, use Check In again: it resolves the recorded operation
and retries the same saved snapshot when needed. It does not silently upload newer
local edits as the old operation. If the server already committed, the result is
recovered without another dataset or checkout release. Local edits are preserved
and reported as not included.

If a pending attempt's checkout was renewed or replaced, the command offers to
keep its snapshot or explicitly start a new operation from the current document.
The old uncommitted snapshot is archived for review. No passwords/tokens are
written into recovery journals. See [Phase 5 details](../../docs/phase5-reliable-checkin.md).

## Material descriptions (0.8.1)

Use **Assign Material / Set Description…** with an owned Working P/A document.
Parts select M catalog entries; assemblies accept free text. No geometry selection,
quantities or density are required. The Description tree column shows both.
Save/upload remains explicit. Backend migration 14 is required. See
[usage and revision behavior](../../docs/material-management.md).

## Physical materials and mass (0.9.0)

Use **Register Raw Material…** for a description plus a native material selection,
or **Link Physical Material…** for an existing M record. Density is automatic.
Selecting that M record with **Assign Material / Set Description…** applies the
native density snapshot and calculates part mass. Read **PDMPartMassKg** in the
managed metadata properties or the source-published mass in the web Description
tab. Existing entries without a link continue working without mass. Backend
migration 15 is required; [details and limitations](../../docs/material-management.md).

## Supplier reference mass (0.10.0)

Structured S registration attempts verified Fabory lookup automatically; explicit
catalog association/reassociation reuses saved reference mass or attempts lookup
under an owned Working checkout. Unsupported specifications and supplier outages
do not block registration. Released references remain unchanged. The web
Description tab displays mass/provenance and supports administrator CSV import.
See [coverage, workflow and API](../../docs/supplier-reference-mass.md).

## Upgrade and verification

Use the [upgrade checklist](../../docs/upgrade-and-validation.md). Existing
matching description-only CAD metadata is upgraded during upload/check-in
preparation, including reconstruction of native mass evidence. Conflicting local
material edits still need reconciliation. Selecting an updated M physical link
for an existing P revision remains explicit. Assembly mass totals and TechDraw
BOM tables are not implemented.

## Standard-part mass fallbacks (0.11.0)

When supplier lookup has no saved result, normal Fasteners registration/association
can estimate mass from one valid solid using the selected material's explicit
reference density. The web Description tab labels the result **Estimated from CAD**
and shows its density/thread basis. Unknown materials/invalid shapes stay unknown.

The registration form has optional **Enter mass manually if no supplier match**
controls. For existing Working S entries, the web Description tab's **Enter mass
manually** accepts grams per piece and an optional note under an owned checkout.
Saved supplier references are protected; manual values are not automatically
replaced. Released records require a new revision for changes. See
[reference densities, API and limits](../../docs/supplier-reference-mass.md).
