# Phase 3 — Local workspace and CAD reference integrity

Phase 3 is implemented for the bounded `freecad-app-link-v1` profile. Phase 4
has not started. See [ADR-004](decisions/ADR-004-cad-workspace-references.md) for
the identity model, supported structures and failure semantics.

## Changes and rationale

- Reuse all nine Workbench commands, the Phase 2 worker engine and existing HTTP
  contracts. New workspace, FCStd and GUI adapter modules keep HTTP/filesystem
  work off the GUI thread and FreeCAD document operations on it.
- Fork source files into managed working copies. Snapshot and verify uploads;
  reject dirty/unuploaded child dependencies. Create Next Revision forks again.
- Add a permission-checked, immutable dataset reference manifest and SQLite
  migration 6. Preserve earlier migrations, metadata and blob storage.
- Retrieve explicit native snapshots into new configurations with verified cache,
  rewritten relative paths and exact document/object validation. Missing, corrupt
  or inaccessible dependencies fail before opening the assembly.
- Mark configuration preparation/completion explicitly. Retry interrupted
  retrieval without replacing local work; retain unknown locks for inspection.

## Validation

- Backend: **29 passed**, including existing regressions, version 5 → 6 metadata
  and byte preservation, permissions, immutable manifests, cycles, HTTP validation
  and concurrent competing manifest attachments.
- Addon: **88 passed**, including deterministic packaging, isolated imports,
  official vendored manifest schema validation, workspace process exclusion,
  snapshot races, dirty dependencies, cache integrity, cancellation and failed
  finalization. Ruff passes for the addon and new backend service/tests.
- Real FreeCAD: Linux FreeCAD **1.1.4**, Python **3.11.14**, Qt **6.8.3**, isolated
  HTTP server with disposable users/projects/data. Automated dialog choices;
  GUI-thread workflows and adapters executed in the real GUI. Results are in
  [the live report](validation/freecad-phase3-2026-10-29.json).
- Existing user documents, credentials and production data were not used as test
  fixtures. Source CAD originals and previous revision files were hash-checked.

The full backend Ruff invocation reports existing repository-wide import/style
and FastAPI `Depends` warnings. This increment does not claim a clean global
lint baseline; the addon and new backend modules pass their checks.

## Acceptance and limits

Supported nested/repeated links reconstruct exact historical CAD geometry,
including same-basename components, preserved placements and relocated relative
paths. Failure/retry and denied-dependency tests publish no false complete graph.
No engineering BOM extraction or quantity synchronization is claimed. Other
FreeCAD/OS versions, third-party assembly adapters and crash/power-loss durability
need additional validation. Clean-start and visual UX checks remain manual after
restarting FreeCAD; live testing used module reload in an existing session.

The additive API requires restarting an updated server and applying migration 6
before using addon 0.3.0. Back up the database with SQLite's backup API and preserve
the immutable file directory together. A downgrade must restore a consistent
backup; no destructive down migration is provided.

Recommended next phase: Phase 4, define supported assembly adapters and explicit
occurrence-to-BOM mapping/quantities before enabling extraction or synchronization.
Phase 5 still owns atomic check-in, fencing, idempotency and uncertain mutations.
No commit, push, public release or production deployment is part of this phase.

## Local development installation

Addon 0.3.0 was installed in both existing user profiles with the prior addons
backed up outside `Mod`. The local development server was restarted after a
SQLite backup at `var/backups/phase3-before-20261030T005345Z/forgepdm.sqlite3`.
Migration 6 applied successfully; every existing metadata row and stored CAD
blob hash matched the pre-upgrade snapshot. The original FreeCAD session still
read Prototype Project and its existing catalog after restart. This was a local
development update, not a production deployment or repository push.
