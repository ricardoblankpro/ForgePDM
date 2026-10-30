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

The output is `clients/freecad/dist/ForgePDM-0.3.0.zip`. Create a `ForgePDM`
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
3. **Acquire / Renew Checkout**, **Check In Current Revision**, and **Release Current Revision** manage the current revision. Check-in uploads the saved native file first and then releases the checkout. The intended workflow is check-in before release; release prerequisites remain enforced by the existing backend.
4. **Create Next Revision** creates the next Working revision in a separate managed file, updates the local metadata and uploads its native snapshot, preserving the previous revision file.
5. **Download Item / Assembly** searches by item number, name or description (blank to browse), offers pages of matching items, then lets you select a revision, including historical revisions. Select an exact native snapshot if several exist. It retrieves the pinned CAD reference graph into a new configuration and verifies external links before completion. Missing/inaccessible components stop retrieval before opening the assembly.
6. **Show ForgePDM BOM** displays the current revision's recursive BOM.

The API upload accepts one file per Dataset. Project authorization and all PDM
rules remain on the server. Downloads require access to every referenced
component revision. Internal UUIDs are carried by the client; you do not need
to enter them when selecting projects, items or revisions.

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
separate operation planned for Phase 4; an empty BOM is not proof of consistency.

## Current limits

Network requests and file transfers run in a worker with progress reporting.
Other ForgePDM commands are disabled while a workflow is active, while FreeCAD's
event loop remains responsive. Cancellation stops subsequent steps and removes
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

Upload, manifest attachment and check-in remain separate HTTP operations. A
failed or timed-out operation may leave an uploaded dataset; inspect server state
before retrying. Atomic check-in and mutation idempotency are Phase 5. Only
native CAD files are transferred automatically, and the verified-cache download
publication requires filesystem hard-link support. Local read-only protection
is advisory. Third-party proxies, external textures and other CAD adapters are
not certified. Windows, macOS and network shares remain unverified.

Version 0.3.0 requires the Phase 3 backend manifest endpoints and additive SQLite
migration 6. Back up the database and immutable files before updating/restarting
the server. The backend still runs separately from FreeCAD. Restart FreeCAD after
updating the addon. See [Phase 3 validation](../../docs/freecad-addon-phase3.md).

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
