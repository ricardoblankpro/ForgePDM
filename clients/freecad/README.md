# ForgePDM FreeCAD Workbench

This is a thin FreeCAD client for the ForgePDM HTTP API. It keeps authentication and PDM rules on the backend; the Workbench only saves local documents, calls API operations, and adds a hidden `ForgePDM_Metadata` object to associate a FreeCAD document with its item and revision IDs.

## Install

The addon uses FreeCAD's modern `freecad.forgepdm` namespace. The declared
initial target is FreeCAD 1.0+ with embedded Python 3.11+; real runtime validation
is still pending. No ForgePDM backend package, pip installation or network access
is required to load the Workbench. A reachable server is needed for its commands.

Build an addon-only archive from the repository root:

```sh
uv run --project clients/freecad --extra dev python clients/freecad/tools/addon.py check
uv run --project clients/freecad --extra dev python clients/freecad/tools/addon.py build
```

The output is `clients/freecad/dist/ForgePDM-0.1.0.zip`. Create a `ForgePDM`
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

1. **Log In** asks for the server URL, username, and password. The bearer token stays in memory for this FreeCAD session; log in again after restarting FreeCAD or when the token expires.
2. **Create / Upload Current Document** saves the active document. If it has no ForgePDM metadata, the command creates an Item (part or assembly), optionally using a project UUID, adds hidden item/revision metadata, and uploads a `native_cad` Dataset.
3. **Acquire / Renew Checkout**, **Check In Current Revision**, and **Release Current Revision** manage the current revision. Check-in uploads the saved native file first and then releases the checkout. The intended workflow is check-in before release; release prerequisites remain enforced by the existing backend.
4. **Create Next Revision** creates the next Working revision, updates the local metadata, saves, and uploads the native CAD file.
5. **Download Item / Assembly** asks for an item UUID, downloads the current native CAD file and native files for BOM component revisions, and opens the selected item.
6. **Show ForgePDM BOM** displays the current revision's recursive BOM.

The API upload currently accepts one file per Dataset. For project users, enter the project UUID when creating an Item; projectless Items are administrator-only. Download also requires access to every referenced component revision.

## Current limits

The Workbench does not search Items by number yet, so download starts from an Item UUID. It downloads each BOM revision under an item/revision-based filename but does not rewrite FreeCAD's internal external-link paths. Assemblies whose linked documents depend on their original local filenames may need those references relinked in FreeCAD. Only the native CAD Dataset is transferred automatically; drawings and neutral exports remain available through the API but are not yet exposed in the Workbench.

The current HTTP operations still run synchronously in command handlers. UI
responsiveness, managed workspaces and automatic reference repair are deferred;
modern packaging does not change those existing limitations.

## Development resources

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
