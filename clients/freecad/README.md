# ForgePDM FreeCAD Workbench

ForgePDM connects FreeCAD to a separately running PDM server. The Workbench
provides a persistent item browser, exact CAD snapshot retrieval, managed
workspaces, checkout/check-in/revisions, component and material workflows,
shared BOM views, TechDraw tables and source-pinned PDF publication.

## Install and use

- [Installation and connection](../../docs/user/install.md)
- [FreeCAD workflow and workspaces](../../docs/user/freecad.md)
- [Components and Fasteners](../../docs/user/components.md)
- [Materials and component mass](../../docs/user/materials.md)
- [BOM views and assembly mass](../../docs/user/bom.md)
- [TechDraw tables and PDFs](../../docs/user/drawings.md)
- [Web workspace](../../docs/user/web.md)
- [Troubleshooting](../../docs/user/troubleshooting.md)
- [Server setup, upgrades and recovery](../../docs/operations/server.md)

Build from the source repository root:

```sh
uv run --project clients/freecad --extra dev --locked python clients/freecad/tools/addon.py check
uv run --project clients/freecad --extra dev --locked python clients/freecad/tools/addon.py build
```

Use the versioned archive path printed by the build. Extract into a fresh
`Mod/ForgePDM` folder, preserving open edits/workspaces and backing up the prior
installation. The layout must contain `package.xml` and
`freecad/forgepdm/init_gui.py`. Restart FreeCAD after a normal replacement.

The build includes these same guides under `Documentation/` and adapts their
links for offline reading. Backend code, tests and development tooling stay out
of the addon. Do not install the backend or another Qt binding inside FreeCAD.

## Compatibility and distribution

The declared minimum is FreeCAD 1.0 / Python 3.11. Native acceptance has used Linux
FreeCAD 1.1.4 / Python 3.11.14 / Qt 6.8.3; other runtime/platform combinations need
acceptance. The archive is a manual-install preview, with a separate reachable
backend required for PDM operations. See [current delivery](../../DEVELOPMENT_STATUS.md),
[release preparation](../../docs/development/releasing.md) and [LGPL-2.1-or-later license](LICENSE).

Contributors should read [the contributor guide](../../CONTRIBUTING.md),
[architecture](../../docs/development/architecture.md) and
[schema provenance](tools/vendor/README.md). The monorepo is the source of truth;
its nested addon directory is not yet an approved Addon Manager distribution source.
