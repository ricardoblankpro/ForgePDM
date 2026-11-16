# Install the FreeCAD addon

The Workbench is a client of a separately running ForgePDM server. Install the
server using [the operations guide](../operations/server.md), or obtain its URL
and an account from your administrator. Current versions and verified runtime
coverage are recorded in [development status](../../DEVELOPMENT_STATUS.md).

## Build and install

From the source repository root:

```sh
uv run --project clients/freecad --extra dev --locked python clients/freecad/tools/addon.py check
uv run --project clients/freecad --extra dev --locked python clients/freecad/tools/addon.py build
```

Use the archive path printed by the build command. Preserve open edits, back up
the existing addon, then extract into a fresh `Mod/ForgePDM` directory. The layout
must include:

```text
Mod/ForgePDM/package.xml
Mod/ForgePDM/freecad/forgepdm/init_gui.py
```

Avoid an extra nested ForgePDM folder. Find the active user directory from
FreeCAD's Python console with `App.getUserAppDataDir()` and use its `Mod` folder.
Keep CAD workspaces outside the addon installation. Replace an installation
rather than overlaying old files; restart FreeCAD after a normal upgrade.

## Connect

Select **View → Workbench → ForgePDM**, then **Log In**. Enter the server URL,
username and password. The local default URL is `http://127.0.0.1:8000`.
The addon remembers URL, username and timeout; passwords and bearer tokens stay
in memory. Expired or revoked sessions require sign-in again.

The addon uses the namespaced `freecad.forgepdm` loader and FreeCAD-provided Qt.
It does not require the backend package or a separate Qt binding inside FreeCAD.
A running server is needed for PDM commands, not for importing the base package.

## Support and distribution

The declared minimum is FreeCAD 1.0 with Python 3.11. Native acceptance has used
Linux FreeCAD 1.1.4 / Python 3.11.14 / Qt 6.8.3. Other platforms, network shares
and runtime combinations need acceptance before being advertised as supported.
This archive is a manual-install preview. Public Addon Index distribution still
requires the decisions in [release preparation](../development/releasing.md).
Continue with [the FreeCAD workflow](freecad.md).
