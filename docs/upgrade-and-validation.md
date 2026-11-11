# Upgrade and validation — addon 0.14.0 / schema 16

The backend runs separately from FreeCAD. Use Python 3.11+ and `uv`; the native
material workflow is validated on Linux with FreeCAD 1.1.4. Other FreeCAD/platform
combinations have not received the same acceptance coverage.

## Back up and upgrade

1. Finish or preserve local edits. Record open documents/checkouts; keep CAD
   workspaces outside the addon directory. A backup is not a check-in.
2. Stop the backend before taking a consistent SQLite backup and copying the
   corresponding `FORGEPDM_FILE_ROOT` contents. Defaults are `var/forgepdm.sqlite3`
   and `var/files`. Back up the installed addon directory as well. Preserve the
   original database, files and addon together for rollback.
3. Update the checkout and run `uv sync --group dev --locked`.
4. Build the addon with:

   ```sh
   uv run --project clients/freecad --extra dev --locked python clients/freecad/tools/addon.py check
   uv run --project clients/freecad --extra dev --locked python clients/freecad/tools/addon.py build
   ```

   The archive is `clients/freecad/dist/ForgePDM-0.14.0.zip`. Replace the previous
   `Mod/ForgePDM` installation with the archive contents; do not overlay old files.
   Restart FreeCAD after a normal installation. Do not install the backend package
   or another Qt binding into FreeCAD.
5. Start the backend using its existing database/file-root configuration:

   ```sh
   uv run uvicorn forgepdm.main:app --app-dir src --host 127.0.0.1 --port 8000
   ```

   Startup applies unapplied SQLite migrations transactionally. The current schema
   is 16. Migration 13 extends the shared catalog to M; 14 adds simple descriptions;
   15 adds physical links and native mass evidence; 16 adds S mass references.
   Addon 0.11.0 added fallback statuses/optimistic tokens using that existing table;
   upgrade backend code as well even though the schema version stays 16.
   Earlier migrations remain part of a clean install. No existing part material
   or supplier mass is inferred. Refresh the browser after updating web assets.
6. Verify `/health`, sign-in, project/catalog access, historical BOM pins and a
   disposable working-copy upload/download. Check SQLite `PRAGMA integrity_check`
   and `PRAGMA foreign_key_check` on the upgraded database before wider use.

Native density snapshot cards live in the active FreeCAD User material library's
`ForgePDM` directory. Original library cards are not overwritten. Download rebuilds
missing managed cards from the frozen snapshot. Retain workspaces and original
material libraries when backing up engineering work.

Restoring a backup is an offline operation: stop the backend and restore the
matching database, blob store and addon versions. Restoring only SQLite or
starting an older backend on a migrated database is not a supported rollback.
Backup automation/disaster recovery and PostgreSQL deployment remain future work.

## Configuration

| Variable | Purpose / default |
|---|---|
| `FORGEPDM_DATABASE` | SQLite path; `var/forgepdm.sqlite3` |
| `FORGEPDM_FILE_ROOT` | Immutable blob root; `var/files` |
| `FORGEPDM_MAX_UPLOAD_BYTES` | Maximum upload; 1 GiB |
| `FORGEPDM_SUPPLIER_LOOKUP` | `1` enables live Fabory lookup (default); `0` disables it while preserving CSV lookup, CAD/manual fallbacks and saved references |

Supplier lookup performs outbound HTTPS only for supported explicit Fabory pages
and robots policy. It does not require a supplier account or purchase anything.
It is optional and availability-dependent, not an official supplier API/feed.
See [coverage and CSV data](supplier-reference-mass.md).

## Automated checks

Run the checks used by the GitHub workflow from the repository root:

```sh
uv run --group dev --locked pytest tests -q
uv run --project clients/freecad --extra dev --locked pytest clients/freecad/tests -q
uv run --project clients/freecad --extra dev --locked ruff check clients/freecad
uv run --project clients/freecad --extra dev --locked ruff format --check clients/freecad
uv run --project clients/freecad --extra dev --locked python clients/freecad/tools/addon.py check
uv run --project clients/freecad --extra dev --locked python clients/freecad/tools/addon.py build
node --test tests/web/model.test.mjs
uv build
```

Backend tests isolate databases/storage and disable live supplier calls; provider
parsing, authorization, unit conversion, outage behavior and API enrichment use
controlled fixtures. Addon pytest uses mocked CAD/Qt; it does not prove native
geometry behavior. Generated archives, databases, credentials and CAD files are
not committed to Git.

## Browser and native acceptance

Use a disposable server and data directory, not your normal engineering data:

```sh
uv run python tests/web/serve.py --case /tmp/forgepdm-web-qa-case
```

This stays running and creates private fixture credentials. Install Playwright
outside the repository, then run the existing browser and simple-description checks:

```sh
npm install --ignore-scripts --no-audit --no-fund --prefix /tmp/forgepdm-web-qa playwright-core
export FORGEPDM_PLAYWRIGHT=/tmp/forgepdm-web-qa/node_modules/playwright-core/index.mjs
node tests/web/browser.mjs /tmp/forgepdm-web-qa-case
node tests/web/materials-browser.mjs /tmp/forgepdm-web-qa-case
```

Chrome is required; these new browser fixtures default to `/usr/bin/google-chrome`.
They write reports/screenshots under the disposable directory. Stop the server
when finished. The native harnesses under `clients/freecad/tools/validation/`
are developer fixtures executed inside a running FreeCAD GUI, not pytest tests:

- `simple_descriptions_gui.py`: P/M selection, A free text, tree display and retrieval.
- `physical_materials_gui.py`: native registration/linking, final-solid mass,
  recompute, publication, legacy-copy upgrade and missing-cache recovery.
- `mass_fallback_gui.py`: real Fasteners solid estimate, unknown material and optional
  manual registration. Run with a fresh disposable backend with
  `FORGEPDM_SUPPLIER_LOOKUP=0`; its `MASS_FALLBACK_QA_CASE` global can select the
  case directory. Then run `tests/web/mass-fallback-browser.mjs` against the same
  directory once; it intentionally edits only those disposable records.
- `reference_mass_gui.py`: controlled S registration with live Fabory lookup,
  reference reuse and Released immutability. Use a fresh fixture server at
  `/tmp/forgepdm-reference-mass-qa`; it expects source checkout
  `/home/ricardoblank/Development/ForgePDM` unless adapted for another machine.
  After its report exists, run `node tests/web/reference-mass-browser.mjs
  /tmp/forgepdm-reference-mass-qa` to check the reference UI.

Inspect each native harness's source/configuration first: some retain development
paths or need an earlier browser fixture report. Live supplier acceptance requires
outbound access and can legitimately yield unavailable data. These scripts create
synthetic records only on their disposable server and preserve existing GUI
session/documents. They do not replace a clean-start/platform acceptance run.

Current evidence and limitations are linked from [DEVELOPMENT_STATUS.md](../DEVELOPMENT_STATUS.md).

Addon 0.12.0 requires the updated assembly-mass API despite unchanged schema 16.
See [assembly mass](assembly-mass.md) for published-BOM scope and limitations.
