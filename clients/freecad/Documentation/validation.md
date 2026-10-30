# Phase 1 validation and manual acceptance

The historical checklist below covers Phase 1. For the current Phase 2 addon,
see `docs/freecad-addon-phase2.md` in the repository. The live harness is
`clients/freecad/tests/freecad_phase2_smoke.py`; execute it only through an actual
FreeCAD interpreter with isolated backend credentials supplied as `PHASE2_CASE`.
It is intentionally not part of pytest discovery and is excluded from the ZIP.

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

FreeCAD was not available during initial implementation. On 2026-10-29 the
installed addon was subsequently tested in a live FreeCAD 1.1.4 session through
FreeCAD MCP Bridge (Linux, Python 3.11.14, Qt 6.8.3). All nine commands executed
against an isolated backend, and 34 checks passed, including native CAD
save/reopen, metadata preservation and historical part geometry/hash checks.
Dialog input and notifications were automated; this does not replace visual
inspection or a clean startup test with the backend stopped. See the repository's
`docs/validation/freecad-phase1-2026-10-29.json` for the actual results and scope.
Other runtime/platform combinations remain unverified.

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
