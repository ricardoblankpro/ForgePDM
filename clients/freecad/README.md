# ForgePDM FreeCAD Workbench

This is a thin FreeCAD client for the ForgePDM HTTP API. It keeps authentication and PDM rules on the backend; the Workbench only saves local documents, calls API operations, and adds a hidden `ForgePDM_Metadata` object to associate a FreeCAD document with its item and revision IDs.

## Install

Copy the entire repository folder `clients/freecad/ForgePDM/` into FreeCAD's `Mod` folder as `Mod/ForgePDM/`. The installed folder must contain `InitGui.py`, `Init.py`, and the `ForgePDM` Python package files (`api.py`, `commands.py`, `session.py`, and `ui.py`). Restart FreeCAD after copying:

- Linux: `~/.local/share/FreeCAD/Mod/ForgePDM/`
- macOS: `~/Library/Application Support/FreeCAD/Mod/ForgePDM/`
- Windows: `%APPDATA%\FreeCAD\Mod\ForgePDM\`

Select **View → Workbench → ForgePDM**. The backend must be running and reachable from FreeCAD. The default login URL is `http://127.0.0.1:8000`; use the URL of your ForgePDM host for a separate server.

## Workflows

1. **Log In** asks for the server URL, username, and password. The bearer token stays in memory for this FreeCAD session; log in again after restarting FreeCAD or when the token expires.
2. **Create / Upload Current Document** saves the active document. If it has no ForgePDM metadata, the command creates an Item (part or assembly), optionally using a project UUID, adds hidden item/revision metadata, and uploads a `native_cad` Dataset.
3. **Acquire / Renew Checkout**, **Check In Current Revision**, and **Release Current Revision** manage the current revision. Check-in uploads the saved native file first and then releases the checkout. Release requires a prior check-in.
4. **Create Next Revision** creates the next Working revision, updates the local metadata, saves, and uploads the native CAD file.
5. **Download Item / Assembly** asks for an item UUID, downloads the current native CAD file and native files for BOM component revisions, and opens the selected item.
6. **Show ForgePDM BOM** displays the current revision's recursive BOM.

The API upload currently accepts one file per Dataset. For project users, enter the project UUID when creating an Item; projectless Items are administrator-only. Download also requires access to every referenced component revision.

## Current limits

The Workbench does not search Items by number yet, so download starts from an Item UUID. It downloads each BOM revision under an item/revision-based filename but does not rewrite FreeCAD's internal external-link paths. Assemblies whose linked documents depend on their original local filenames may need those references relinked in FreeCAD. Only the native CAD Dataset is transferred automatically; drawings and neutral exports remain available through the API but are not yet exposed in the Workbench.
