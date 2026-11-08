# FreeCAD validation and manual acceptance

Current client: **0.11.0**, backend schema **16**. The latest checked suites contain
221 backend tests and 364 addon tests; live FreeCAD/browser evidence and scope are
recorded in `DEVELOPMENT_STATUS.md` and the 2026-11-07 material/reference reports.
Use [the current validation/upgrade guide](../../../docs/upgrade-and-validation.md)
for configuration, packaging, native harnesses and browser checks. Addon lint and
format checks match the GitHub workflow; mocked tests remain distinct from native
GUI execution. Assembly totals and TechDraw BOM tables are still deferred.

The historical checklist below covers Phase 1. For the Phase 4 assembly work,
see `docs/freecad-addon-phase4.md` in the repository. The live harness is
`clients/freecad/tests/freecad_phase4_smoke.py`; its module docstring describes
starting a disposable backend and executing it through the actual FreeCAD MCP.
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
Phase 2 added responsive networking. Phase 3 exercised pinned whole-object
App::Link reconstruction in FreeCAD 1.1.4, including nested/repeated links,
historical geometry, relocation and failed-transfer recovery. See
`docs/freecad-addon-phase3.md` and its live report. Other adapters and platforms
remain unverified; clean-start and visual checks above still require a restart.

Phase 4 exercised engineering occurrence selection, BOM replacement consent,
internal repeated links, nested assemblies, historical revision pins and stale
review/CAD-change rejection in the same FreeCAD/Python/Qt runtime. The public
Show BOM command and real dialogs executed against an isolated backend. See
`docs/validation/freecad-phase4-2026-11-01.json`. Other assembly adapters remain
outside the certified profile; atomic check-in/idempotency remain Phase 5.

On 2026-11-01, optional-note check-in was tested through the actual registered
`ForgePDM_CheckIn` command in the running FreeCAD 1.1.4 GUI, using the user's
explicitly authorized open test assembly. Both installed profiles had still been
on addon 0.3.0, and the local backend had the previous required-note API loaded.
The installed addons were backed up and updated; the backend was restarted and
registered command instances refreshed in the running session. The real command
uploaded a native snapshot, posted an empty optional note, preserved the existing
revision note and released the checkout without showing a note prompt. Final
notifications were captured to avoid blocking the automated test; the actual
worker engine and HTTP requests executed. See
`docs/validation/freecad-optional-checkin-2026-11-01.json` for the 11 live checks.

## Toolbar activation fix (0.4.1)

The gray-toolbar issue was reproduced in live FreeCAD 1.1.4: after Show BOM
completed, `Session.busy` was false but every ForgePDM QAction remained disabled.
The asynchronous completion path did not notify FreeCAD to reevaluate `IsActive`.
The worker adapter now calls `FreeCADGui.Command.update()` on entering busy state
and after completion/notification cleanup. Completion clears busy/active-job state
before closing the progress dialog. Refresh happens in `finally`, including when
reporting fails, and follows session invalidation so protected commands stay
disabled for expired sessions. Command predicates remain authoritative.

This uses FreeCAD's public command-update API; no unrelated command, document
recompute, forced action enablement or periodic refresh loop is introduced. The
official binding delegates to the main window's scheduled activation update:
[FreeCAD 1.1 command binding](https://github.com/FreeCAD/FreeCAD/blob/1.1.0/src/Gui/CommandPyImp.cpp).
No upstream implementation code was copied.

The 0.4.1 addon passed **123 automated addon tests**, including success, worker
failure, cancellation, HTTP 401, immediate completion and notification failure
cleanup. In real Linux FreeCAD **1.1.4**, Python **3.11.14**, Qt **6.8.3**, the
actual Show BOM QAction was triggered twice consecutively. All nine actions
reactivated after each completion without any unrelated command. Additional
live checks covered timeout, cancellation, immediate completion and HTTP 401
with an isolated invalid-token client. The real login was restored and the
active assembly was retained; these tests made no CAD/server writes. Final
error/cancellation notifications were captured to avoid blocking the harness.

The **19 live assertions** and before/after QAction snapshots are recorded in
`docs/validation/freecad-toolbar-2026-11-01.json`. The reproducible harness is
`clients/freecad/tests/freecad_toolbar_smoke.py`; invoke `run(App, Gui)` through
MCP with a logged-in session and active managed document. Both installed user
profiles were backed up outside `Mod` and updated. The running session reloaded
the worker adapter; a restart will load the same fix from the installed files.

## Native Assembly BOM support (0.4.2)

The native Assembly container and standard Joint/GroundedJoint objects no longer
block extraction of direct whole-object App::Link components. Joints remain
constraints and are excluded from quantities. The bounded adapter rejects
unknown proxies, unsupported assembly types, nested local containers and stray
links with contextual errors. All existing pinned-snapshot and review checks apply.

The addon suite passes **131 tests**. Live FreeCAD **1.1.4** testing on the user's
authorized A000001 test assembly uploaded its owned Working component copies and
then the parent, selected the two components in the actual synchronization dialog,
and approved the initially empty engineering BOM. Reopened Show BOM displayed
P000004 Rev A × 1 and P000005 Rev A × 1. The **15 live checks** cover saved quantities,
exact revisions, unchanged native file hashes/placements/grounding during
synchronization, and toolbar reactivation. See `docs/freecad-builtin-assembly.md`
and `docs/validation/freecad-native-assembly-bom-2026-11-01.json` in the repository.
Only the documented bounded structure is certified; this is not blanket support
for every built-in or third-party Assembly feature.

## Downloaded component saved state (0.4.3)

Native reconstruction previously called `App.Document.save()` after its own
metadata/relink edits. In FreeCAD 1.1.4, this can leave `Gui.Document.Modified`
set even after the file is saved and hashed. BOM extraction then misidentified
unchanged retrieved components as unsaved. Acquiring the assembly checkout cannot
change this separate GUI state.

The loader now saves its owned reconstructed copies through `Gui.Document.save()`
and requires clean state before configuration completion. It does not blindly
clear flags or trust disk hashes as proof of unchanged in-memory content. Genuine
edits remain blocked; failed cleanup preserves GUI-modified documents even after
recompute clears touched flags. Component errors now identify item/revision.

Automated addon results: **136 passed**, including clean metadata saves, failed
saves, genuine edits after recompute and dirty-document retention. In real Linux
FreeCAD **1.1.4**, Python **3.11.14**, Qt **6.8.3**, a temporary clone of the user's
current assembly reconstructed P000004 Rev B, P000005 Rev A and P000006 Rev A
without false modification flags. Root/child snapshot verification and the owned
checkout check passed. A deliberate label edit on a disposable component was
rejected by BOM extraction and retained during cleanup. All original user files,
open documents and modification flags were preserved; the original active
assembly was restored. No server metadata or engineering BOM was changed.

See the **7 live checks** in
`docs/validation/freecad-clean-component-state-2026-11-01.json` and the harness
`clients/freecad/tests/freecad_clean_state_smoke.py`. Both installed profiles were
backed up and updated to 0.4.3, and the running CAD adapter was reloaded. Previously
opened documents retain their old flags: retrieve/reopen them once through the
corrected ForgePDM loader. No automatic discard/reload of user work is performed.

## Tree occurrence labels (0.5.0)

Managed links display ITEM-REVISION|OCCURRENCE. A versioned per-document registry
retains high-water marks and ownership; copied properties are reseeded and deleted
indices are not reused. Labels use pinned metadata, never latest lookup or parsed
display text. Upload/retrieval apply presentation before saving/hash finalization.
The additive Refresh Tree Labels command checks the current owned checkout. A
debounced GUI observer handles insertion under cached, unexpired local permission
after native transactions finish; check-in/release revoke that cached permission.

Real FreeCAD **1.1.4**, Python **3.11.14**, Qt **6.8.3** testing passed 18 disposable
CAD assertions, 12 isolated HTTP/CAD workflow assertions and 7 current-assembly
assertions. Tests cover copy/delete/reorder, native save/reopen, subassembly scopes,
automatic insertion, revoked permission, upload, next revision, historical pinned
labels/UUIDs and unchanged geometry/BOM. The current tree widget rendered all
four requested occurrences; its working file was backed up and uploaded with the
new presentation metadata. Immutable snapshots and component files were preserved.

The standalone CAD observer test injects a fixture lease; actual authenticated
checkout checks are exercised by the current-document command and isolated backend
workflows. Native raw file-open resets the document heading from its filename;
managed projection reapplies that heading without reallocating link indices.
The final automated suites passed **160 addon tests** and **54 backend tests**;
targeted addon lint/format and standalone manifest/build checks pass.
See `docs/freecad-tree-labels.md`, ADR-006 and
`docs/validation/freecad-tree-labels-2026-11-01.json` for scope and evidence.
