# Phase 1 validation and manual acceptance

## Automated checks

From the repository root:

```sh
uv run --project clients/freecad --extra dev python clients/freecad/tools/addon.py check
uv run --project clients/freecad --extra dev pytest clients/freecad/tests -q
uv run --project clients/freecad --extra dev ruff check clients/freecad
uv run --project clients/freecad --extra dev ruff format --check clients/freecad
uv run --project clients/freecad --extra dev python clients/freecad/tools/addon.py build
uv run --group dev pytest tests -q
```

Addon tests use mocked FreeCAD/Qt modules and a fake HTTP transport. They verify
registration, installed imports and request compatibility, not actual GUI or CAD
execution. No runtime dependency is installed into FreeCAD by these commands.

## Required real FreeCAD validation

FreeCAD was not available in the implementation environment: no executable was
found on PATH and `/opt/freecad` was empty. FreeCAD 1.0+ with Python 3.11+ is the
declared initial target, not a verified runtime matrix. Qt 5/PySide2 and
Qt 6/PySide6 imports have mocked coverage; platform compatibility remains pending.

1. Record OS, FreeCAD build, embedded Python and Qt/PySide versions.
2. Remove the old `Mod/ForgePDM` installation and extract the new archive into
   a fresh `Mod/ForgePDM` directory; restart FreeCAD with the server stopped.
3. Verify one ForgePDM Workbench appears, with an icon and no startup error.
4. Activate it and inspect the Python console:

   ```python
   expected = {
       "ForgePDM_Login",
       "ForgePDM_Logout",
       "ForgePDM_Upload",
       "ForgePDM_Checkout",
       "ForgePDM_CheckIn",
       "ForgePDM_Release",
       "ForgePDM_NewRevision",
       "ForgePDM_Download",
       "ForgePDM_ShowBOM",
   }
   assert expected <= set(Gui.listCommands())
   assert "ForgePDMWorkbench" in Gui.listWorkbenches()
   ```

5. Switch away/back and verify no duplicate menus/toolbars or commands.
6. Reopen a previous document and inspect `ForgePDM_Metadata` and its four
   existing properties without saving over the original.
7. Start a disposable backend and smoke-test login/logout and the existing
   create/upload/checkout/check-in/release/revise/download/BOM-display flows.
8. Verify the Workbench loads without the backend Python package installed.
9. Change the UI language and verify English fallback; compiled translations
   can be added after reviewed translations exist.

Do not mark runtime acceptance complete until this checklist has actual results.
Assembly reference reconstruction and responsive networking remain later phases.
