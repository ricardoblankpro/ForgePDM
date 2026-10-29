# Phase 1 — FreeCAD addon modernization

## Scope and outcome

Migrate the existing Workbench into `clients/freecad/freecad/forgepdm` using the
official modern namespace layout. Preserve all nine command IDs, backend API
contracts and the `ForgePDM_Metadata` object with `ItemId`, `RevisionId`,
`ItemNumber` and `RevisionLabel`. No backend or legacy reference code changed.

The old loader files are removed rather than retained as a second entry point.
Initialization registers one Workbench and defers command/Qt imports until
activation. Resource resolution is independent of the working directory.
Commands receive an original SVG icon and translatable menu labels/tooltips.
An English source catalog and runtime translation path are provided; there are
no reviewed translations or compiled catalogs yet.

`package.xml` and the standalone `pyproject.toml` describe a dependency-free
runtime client. Development dependencies and their lockfile are separate from
the backend. The manifest uses format 1 and the official template namespace;
offline validation binds the pinned official v1.0 schema with standard XSD
chameleon inclusion. See the schema provenance and compatibility notes in
`clients/freecad/tools/vendor/README.md`.

Root `pytest.ini` keeps default backend test discovery scoped to `tests/`.
The addon's separately invoked test project needs its own development
dependencies, which are deliberately absent from the backend environment.

The deterministic ZIP builder validates metadata and packages only client source,
resources and user documentation. It excludes backend code, tests, tools, caches,
databases and legacy files. A GitHub Actions workflow repeats the addon checks;
it was added locally and has not been executed on GitHub or published.

## Validation evidence

On 2026-10-29, Python 3.11.13:

- Addon tests: **28 passed**. Installed imports run in isolated subprocesses
  without site-packages, using files extracted from the actual ZIP. GUI
  registration tests use mocked FreeCAD/Qt modules, including PySide, PySide2
  and PySide6 import paths. API tests use fake transports.
- Manifest/schema checks: pass with the documented namespace binding.
- Addon Ruff lint and formatting: pass.
- Existing backend suite outside the sandbox: **16 passed in 2.80 seconds**.
  The sandboxed suite timed out at TestClient startup; the same existing test
  stall was observed in the read-only assessment. No backend regression was
  observed in the successful complete run.
- FreeCAD was not executed. No executable was found on PATH, its Python module
  was unavailable, and `/opt/freecad` was empty.

## Acceptance and remaining gates

### Subsequent real FreeCAD execution — 2026-10-29

The installed addon was exercised through FreeCAD MCP Bridge in the running
FreeCAD **1.1.4** session on Linux, with embedded Python **3.11.14** and Qt
**6.8.3**. **34 checks passed**, executing all nine registered commands through
`Gui.runCommand`. Dialog responses and notifications were automated while CAD
operations, Qt widgets and HTTP requests used the real FreeCAD runtime.

The test used a disposable backend/account/database/blob store and temporary CAD
documents. It verified login/logout, upload, checkout, check-in, release,
rejection of uploads to released content, revision B creation, BOM display and
native download. Reopening revision A proved its geometry and metadata remained
unchanged; its downloaded bytes matched the stored SHA-256 hash. The user's
original documents and login session were restored, the temporary server was
stopped and its credentials deleted. The normal backend remained healthy.

The addon suite passed again (**28 tests**) and the complete backend suite passed
outside the sandbox (**16 tests in 2.84 seconds**). A non-blocking Qt `exec_`
deprecation warning was emitted. No application code changed for this execution.
Detailed evidence is in
[the runtime report](validation/freecad-phase1-2026-10-29.json).

The remaining manual scope is clean startup with the backend stopped, visual
inspection/manual dialog entry, and an existing user-document compatibility
check. Non-empty assembly structures, external-reference recovery and other
runtime versions were not tested. These results support moving to Phase 2 after
review; no Phase 2 implementation was started.

### Initial acceptance status (before the MCP execution above)

The initial status below is retained as historical context. A subsequent
read-only-document regression fix is documented at the end of this report.

Automated packaging, isolated imports, nine-command registration under mocks,
resource existence, metadata compatibility and API-contract preservation pass.
The ZIP is ready for a manual installation/loading test.

Actual Workbench loading, manifest parsing, command execution and reopening an
existing CAD document remain **unverified**. Follow
`clients/freecad/Documentation/validation.md`, recording OS/FreeCAD/Python/Qt
versions. The declared FreeCAD 1.0+/Python 3.11+ target is not a tested support
matrix. Real FreeCAD acceptance is still open.

Public distribution is not ready: project code/asset licensing and maintainer
contact need owner decisions, and the nested monorepo is not yet an approved
Addon Manager source. `UNLICENSED` explicitly records the existing license gap.
No external repository, release, deployment, commit or push was created.

Phase 2 is recommended after the manual loading gate: connectivity, session
handling and responsive network operations. It is not implemented here.
Assembly reference reconstruction, workspace isolation and robust atomic
check-in remain later phases; modernization does not claim to fix those risks.

## Read-only document upload regression — 2026-10-29

The user's active `PartDesignExample.FCStd` came from the mounted AppImage under
`/tmp/.mount_.../usr/share/examples/`. Both file and parent directory were
read-only. Upload previously called `document.save()` on that path and failed
before making any backend request.

The client now detects unwritable source files/directories, prompts for a
writable native CAD copy, recomputes before saving and reports save failures
with the destination path and a Save As recovery instruction. Canceling or
selecting an unwritable location stops before Item creation. Writable working
documents retain their in-place-save behavior. Backend rules and API contracts
are unchanged.

Validation: **35 addon tests passed**, including seven save regression cases;
lint and format checks pass. The installed fix was reloaded through MCP and
**37 real FreeCAD checks passed**, including a read-only native source, saving
to a new path, upload, and verification that the original bytes were unchanged.
The user's open document and login session were preserved. The disposable test
backend was stopped and its generated credentials removed. A non-blocking Qt
`exec_` deprecation warning remains. See
[the regression report](validation/freecad-readonly-2026-10-29.json).

Separately, the local `alice` account has no project memberships. The user must
select/provision a project before creating Items as this non-administrator;
authorization was not weakened as part of the file-saving fix.
