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

Use an isolated uv environment outside FreeCAD and invoke pytest through that
Python, so the added binding is visible:

```sh
uv run --project clients/freecad --extra dev --locked --with PySide6==6.8.3 python -m pytest clients/freecad/tests/test_bom_dialog.py clients/freecad/tests/test_drawing_bom_ui.py clients/freecad/tests/test_browser_panel.py clients/freecad/tests/test_open_dialog.py -q
```

The base suite skips those modules without PySide6. Do not install the test
binding in FreeCAD's interpreter. Installed FreeCAD acceptance remains separate.

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

## Documentation and packaging checks

`tools/check_docs.py` checks local Markdown targets/anchors, the current handoff
version and portable harness paths. `addon.py check` validates metadata and schema
provenance; its build generates the addon-only ZIP with canonical user/operations
docs and rewrites their links for the installed layout. Packaging tests verify
self-contained documentation, deterministic output, isolated imports and rejected
invalid manifests/resources. Public release adds the separate metadata gates in
[release preparation](releasing.md).
