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

The output is `clients/freecad/dist/ForgePDM-0.2.0.zip`. Create a `ForgePDM`
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
2. **Create / Upload Current Document** lets you choose an authorized project by number/name for a new Item, saves the active document, attaches hidden item/revision metadata, and uploads a `native_cad` Dataset. Only editable projects are offered; administrators may choose a projectless Item.
3. **Acquire / Renew Checkout**, **Check In Current Revision**, and **Release Current Revision** manage the current revision. Check-in uploads the saved native file first and then releases the checkout. The intended workflow is check-in before release; release prerequisites remain enforced by the existing backend.
4. **Create Next Revision** creates the next Working revision, updates the local metadata, saves, and uploads the native CAD file.
5. **Download Item / Assembly** searches by item number, name or description (blank to browse), offers pages of matching items, then lets you select a revision, including historical revisions. It downloads that native CAD file and files for its explicit BOM component revisions. Missing/inaccessible components stop the workflow before opening the assembly.
6. **Show ForgePDM BOM** displays the current revision's recursive BOM.

The API upload accepts one file per Dataset. Project authorization and all PDM
rules remain on the server. Downloads require access to every referenced
component revision. Internal UUIDs are carried by the client; you do not need
to enter them when selecting projects, items or revisions.

If the current document comes from a read-only location (including bundled
FreeCAD examples inside an AppImage), Create / Upload prompts for a writable
local copy first. Choose a folder you own; the original is not overwritten.
Canceling that save prompt stops the operation before any Item is created.

## Current limits

Network requests and file transfers run in a worker with progress reporting.
Other ForgePDM commands are disabled while a workflow is active, while FreeCAD's
event loop remains responsive. Cancellation stops subsequent steps and removes
partial downloads; a blocked request may need to reach its timeout first.
Short finalization requests cannot be canceled. Cancellation never undoes a
server commit, and failed/uncertain mutations are never retried automatically.
Check the revision/server state before repeating a failed upload or check-in.

CAD save/recompute still runs on the GUI thread. Downloads retain the current
latest-native-dataset selection policy within each explicitly selected revision;
exact dataset/configuration manifests remain future work. External-link paths
are not rewritten, so downloading all components does not guarantee a restored
assembly. Managed workspaces, reference integrity, BOM extraction and atomic
upload/check-in are deferred to later phases. Only native CAD is transferred
automatically. The current no-overwrite download publication requires a
filesystem supporting hard links.

Version 0.2.0 needs the Phase 2 backend catalog endpoints. Restart/update the
server if the client reports that project/item browsing is unsupported. The
backend still runs separately from FreeCAD.

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
