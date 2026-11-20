# Testing and validation tiers

Run checks from the repository root. [Contributing](../../CONTRIBUTING.md) lists
the required commands; the current handoff records recent results. Test tiers
prove different things and should be reported separately.

| Tier | Location | Evidence |
|---|---|---|
| Backend service/API | `tests/test_*.py` | Domain rules, transactions, migrations, authorization and isolated storage |
| Addon unit/contract | `clients/freecad/tests/test_*.py` | Fake CAD/transport, packaging, workflows and data preservation guards |
| Real Qt | Optional PySide6 modules in addon tests | Dialog/event-loop behavior; not native CAD execution |
| Pure web | `tests/web/*.test.mjs` | Display/navigation/decimal helpers without browser dependencies |
| Browser | `tests/web/*-browser.mjs`, `browser.mjs` | Chrome + disposable HTTP/database fixtures |
| Native FreeCAD | `clients/freecad/tools/validation/` | Actual FreeCAD/Qt/CAD workflows, exact snapshots and PDF export |
| Installed runtime | Dated reports | Actual module paths/version plus database/blob/document preservation |

## Optional Qt

On Ubuntu, install the Qt graphics libraries before running these tests:

```sh
sudo apt-get update
sudo apt-get install --yes --no-install-recommends libegl1 libgl1 libopengl0
```

The CI Qt job installs these explicitly and uses `QT_QPA_PLATFORM=offscreen`.
Offscreen execution still needs the shared graphics libraries; missing
`libEGL.so.1` prevents PySide6 widgets from importing before any test runs.

Use an isolated uv environment outside FreeCAD and invoke pytest through that
Python, so the added binding is visible:

```sh
uv run --project clients/freecad --extra dev --locked --with PySide6==6.8.3 python -m pytest clients/freecad/tests/test_bom_dialog.py clients/freecad/tests/test_drawing_bom_ui.py clients/freecad/tests/test_browser_panel.py clients/freecad/tests/test_open_dialog.py clients/freecad/tests/test_localization_ui.py -q
```

The base suite skips those modules without PySide6. Do not install the test
binding in FreeCAD's interpreter. Installed FreeCAD acceptance remains separate.
Include `clients/freecad/tests/test_drawing_balloons_ui.py` for the explicit
balloon adoption and reconciliation dialog.

## Browser fixtures

Start a disposable backend, using a new case directory:

```sh
uv run --group dev --locked python tests/web/serve.py --case /tmp/forgepdm-browser-case
```

In another shell:

```sh
npm install --ignore-scripts --no-audit --no-fund --prefix /tmp/forgepdm-web-qa playwright-core
export FORGEPDM_PLAYWRIGHT=/tmp/forgepdm-web-qa/node_modules/playwright-core/index.mjs
node tests/web/browser.mjs /tmp/forgepdm-browser-case
node tests/web/bom-reports-browser.mjs /tmp/forgepdm-browser-case
```

Set `FORGEPDM_BROWSER` for a different Chrome/Chromium binary. Drivers stay outside
the repository and are not product runtime dependencies. Feature-specific browser
scripts may need earlier fixture reports or intentionally mutate disposable
records; inspect their setup before use. Stop the fixture server afterward.

## Native acceptance

All native harnesses live under `clients/freecad/tools/validation`. Use their
module docstrings/configuration, a running FreeCAD GUI and disposable backend/CAD
fixtures. For example, `freecad_phase4_smoke.py --serve CASE_DIR` creates a minimal
server configuration; `drawing_bom_gui.run(App, Gui, CASE_DIR, shared_views=True)`
executes atomic seed + direct/indented/flattened table/viewer acceptance.
`freecad_atomic_checkin_integration.py` contains the reusable atomic seed.

Load harnesses with `importlib.util.spec_from_file_location` so `__file__` resolves
source-relative paths. Some scripts are historical reproductions or operate on
a selected current document: inspect scope first. No shared runner should quietly
execute production-changing scripts. Record the exact FreeCAD/Python/Qt/OS,
fixture scope, mutations, original-document preservation and installed version.

Keep reports under `docs/validation` only after removing credentials/private
engineering content. Treat their date/runtime as evidence boundaries. Do not
update old reports to make them look current. Native/platform acceptance is not
implied by pytest, schema checks or an archive build.

### Shared thumbnail acceptance

Start a new disposable server in one terminal:

```sh
uv run --locked python clients/freecad/tools/validation/thumbnail_server.py --case /tmp/forgepdm-thumbnails-case
```

In the running FreeCAD GUI, load each harness from the repository and run its
`run(App, Gui, CASE_DIR)` function in this order:

1. `freecad_atomic_checkin_integration.py`: seeds actual native upload/check-in
   snapshots and tests durable recovery against the disposable server.
2. `thumbnails_gui.py`: verifies isometric capture, orthographic/perspective
   camera preservation, selection/visibility/dirty state, linked-component guards
   and the authorized native browser. It preserves pre-existing documents.

Use `importlib.util.spec_from_file_location` as described above. Both harnesses
use `/tmp/forgepdm-thumbnails-case/connection.json`; do not replace its paths or
credentials with production values. They write reports/screenshots inside the case.
With that fixture populated, use the external Playwright driver from the browser
setup above:

```sh
node tests/web/thumbnails-browser.mjs /tmp/forgepdm-thumbnails-case
```

This checks source-specific image display, upload selection, missing/stale image
responses, logout cleanup, mobile sizing and CSP. Stop the disposable server when
finished. The [validation index](../validation/README.md#shared-isometric-thumbnails)
records installed-runtime evidence separately from unit/Qt results.

### Backup and restore regression

`tests/test_backups.py` covers online WAL snapshots, corruption, path safeguards,
failed copies, isolated restoration and status/locking. `tests/test_thumbnails.py`
also verifies thumbnail bytes/associations in a restored backup and compatibility
with the prior schema. For scheduled drills against an installation, follow
[operations](../operations/backups.md); a structural drill does not establish
complete disaster-cutover or GUI/platform acceptance.

### Retained native command callbacks

After a development live reload, directly constructing a new command class does
not prove that FreeCAD's existing toolbar/menu callback uses that implementation.
`registered_command_gui.run(App, Gui, CASE_DIR)` probes the actual Upload and
Check In command IDs. It intercepts and closes their workflow generators before
execution, verifies the current implementation and preserves open documents and
session identity. It requires an idle authenticated session with a managed active
document so those registered actions are available. The 0.20.1 dispatch regression
also covers retained-instance state and ordinary/unbound workflows in unit tests.

### Drawing balloon diagnostics

`stable_balloon_fingerprints_gui.run(App, Gui, CONFIGURATION, CASE_DIR)` must run
in a separate FreeCAD process with `FREECAD_USER_HOME` under `/tmp`, a copied
configuration under `/tmp`, no open documents and no production login. The harness
enforces these conditions. Use a separate X display when testing document closure;
do not execute it inside the user's active FreeCAD session. Provide the needed
FreeCAD addons/dependencies in that temporary profile. The harness exercises the
real configuration loader, legacy-target verification, stable BREP evidence,
strict arrow/placement/target failures, save/reopen and the actual PDF exporter.
No source snapshot is uploaded or published. See
[stable evidence](../decisions/ADR-031-stable-balloon-geometry-evidence.md).

`balloon_review_gui.run(App, Gui, CASE_DIR)` creates disposable ordinary and
projection-group views with valid and damaged frozen balloon links. It checks
object-aware diagnostics, native selection, revalidation/cleanup and PDF output.
Compare `before.pdf` and `with-markers.pdf` as raster images; the diagnostic
viewport widgets must not appear in either export. Unit/real-Qt tests cover marker
coordinates, stale selection, document/page changes, signed-out inspection and
visible/cleared viewport paint. Do not enumerate or wrap private TechDraw scene
items; the adapter uses native model coordinates and a child viewport widget.

Coordinate mapping follows the documented implementation in FreeCAD 1.1.0's
[QGIViewBalloon](https://github.com/FreeCAD/FreeCAD/blob/1.1.0/src/Mod/TechDraw/Gui/QGIViewBalloon.cpp),
[QGIView projection-group positioning](https://github.com/FreeCAD/FreeCAD/blob/1.1.0/src/Mod/TechDraw/Gui/QGIView.cpp)
and [Rez conversion](https://github.com/FreeCAD/FreeCAD/blob/1.1.0/src/Mod/TechDraw/Gui/Rez.cpp).
These LGPL-2.0-or-later sources were consulted as references; the Python adapter
and viewport painting were written in this repository. Native acceptance remains
limited to the runtime recorded in the dated evidence.

## Documentation and packaging checks

`tools/check_docs.py` checks local Markdown targets/anchors, the current handoff
version and portable harness paths. `addon.py check` validates metadata and schema
provenance; its build generates the addon-only ZIP with canonical user/operations
docs and rewrites their links for the installed layout. Packaging tests verify
self-contained documentation, deterministic output, isolated imports and rejected
invalid manifests/resources. Public release adds the separate metadata gates in
[release preparation](releasing.md).

### Multilingual descriptions

`tests/test_localization.py` covers source versions, draft/approval/invalidation,
released-item permissions, unknown legacy languages, Unicode search/pagination,
independent material snapshots, proposal compatibility and stable localized BOM
tokens. The optional real Qt suite also includes `test_localization_ui.py`.

`tests/test_unified_descriptions.py` covers canonical text for all four series, manual P assignment/clearing, fixed structured S text and attributed migration of legacy approvals. `tests/web/unified-descriptions-browser.mjs CASE_DIR` checks all four editors against a disposable fixture using the same external Playwright setup.

Against a new `tests/web/serve.py` fixture, run
`node tests/web/localization-browser.mjs CASE_DIR` with the external Playwright
driver described above. The script creates only disposable items/translations. It checks the web comparison editor, target/display language independence, draft/approval states, source-language confirmation, contextual assistance, retained editing buffers, concurrent changes, view-only access and narrow layout. `tests/test_translation_assistance.py` verifies that availability checks do not persist proposals and reuse existing permissions and generation rules.
`localization_gui.run(App, Gui, CASE_DIR)` in the native validation folder checks
the installed HTTP client and a real saved/reopened format-3 TechDraw table. It
preserves pre-existing documents and the production session. These fixtures do
not classify real legacy descriptions or translate existing engineering data.

### Native tree descriptions

`test_tree_status.py` in each test suite covers authorized batch localization,
unchanged legacy status payloads, exact Fasteners association capture and rejection
of old language results. `test_pdm_status.py` checks deduplication, bounded reads,
original fallback and preservation of local description edits.

`tree_descriptions_gui.run(App, Gui, CASE_DIR)` uses a disposable `serve.py` fixture
with `tree-fixture.json` containing an assembly and three associated S revisions
with approved translations. It creates real Fasteners proxies and native tree rows,
compares English/Portuguese/original text with BOM reports, sends a real tooltip
help event over a narrow Description cell, and preserves existing documents/session.

### TechDraw BOM sorting

`test_drawing_bom.py` tests default natural item ordering, numeric/description
sorts, missing values, stable ties, indented subtree preservation, unchanged report
evidence/positions, row notes and legacy formats. The real Qt drawing editor
suite checks preview order, custom-note remapping, presets and existing tables.
`drawing_bom_sort_gui.run(App, Gui, CASE_DIR, prior_model_path=None)` in the native
validation folder creates disposable TechDraw tables, verifies format-4 frozen
save/reopen and PDF export, and preserves existing documents/session. Its optional
prior-addon model path proves safe rejection of unsupported format-4 updates.

### Linked drawing balloons

`test_drawing_balloons.py` covers exact frozen identities, duplicate occurrence
sets, conservative reconciliation and read-only PDF preflight. Command workflow
tests cover cancellation, edit permission, Working lifecycle and document/session/
checkout races. The real Qt suite includes `test_drawing_balloons_ui.py`.

`drawing_balloons_gui.run(App, Gui, CASE_DIR, prior_model_path=None)` requires an
idle empty FreeCAD session and a new `forgepdm-drawing-balloons-qa*` directory.
It creates only disposable native CAD: adoption dialog, expression text, retained
leader/style, multiple tables/balloons, atomic failure/undo/redo, native save/reopen,
managed FCStd integrity inspection, PDF output and unresolved/orphan handling.
PDF exporter acceptance supplies a fixture configuration opener; it exercises
the real export gate/cleanup but does not claim an HTTP publication. The optional
prior-addon model proves format-5 edit rejection. Preserve the initial session.

### Automatic balloon attachments

`test_balloon_auto.py` checks contact/ambiguity policy, restoration exclusion,
bubble changes and undo/redo queue suppression. Automatic command tests cover
permission, lease, session, geometry and table changes between checks.
`automatic_balloons_gui.run(App, Gui, CASE_DIR)` requires an empty session and a
new `forgepdm-auto-balloons-qa*` directory. It uses disposable pinned links and a
fixture permission/checkout/workspace transport, verifies the actual native
TechDraw balloon command, arrow movements, projection coordinates, overlapping
candidates, native persistence and PDF output. Chooser results are supplied by
the fixture; no production CAD, HTTP publication or server BOM mutation occurs.
