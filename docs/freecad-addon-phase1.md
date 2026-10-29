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
