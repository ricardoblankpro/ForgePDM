# Phase 2 — Initialization, API connectivity and catalog browsing

## Objective and implemented scope

Make the installed addon usable without internal UUID entry, and keep network
latency from freezing FreeCAD. Preserve the existing nine command IDs, document
metadata and authoritative backend editing rules.

Reuse the standard-library transport, Workbench initialization, hidden metadata,
authentication, project memberships, file transfers and existing revision/BOM
services. Add a read-only catalog service, a testable workflow engine and a thin
Qt adapter. ADR-003 records the threading, cancellation and API contracts.

## Changes and affected components

- Backend `application/catalog.py`, API routes and application wiring provide
  permission-filtered paginated project/item/revision reads. No migration or
  existing write endpoint changed.
- Addon `jobs.py` runs yielded requests in a worker and resumes command workflows
  on the caller/GUI thread. `tasks.py` integrates QTimer polling, progress,
  cancellation, busy state, diagnostics and session recovery.
- Existing commands now yield every HTTP/file-transfer operation. CAD operations
  and dialogs remain on the GUI thread. Project selection uses authorized
  number/name labels; download searches items and chooses an explicit revision.
- Settings remember server, username and timeout, excluding passwords/tokens.
  Login validates responses; local/server expiry clears the session. Transport
  errors have stable codes and readable messages; mutations are not retried.
- Transfer staging is unique per download. Cancellation removes partial files;
  same-directory hard-link publication refuses to replace an existing target.
- Addon metadata is 0.2.0. Packaging/import checks and the offline manifest schema
  are retained. CI configuration includes separate backend and addon jobs.

## Acceptance criteria and verification

1. Existing command IDs and document metadata remain compatible.
2. GUI timers continue firing during delayed HTTP and timeout handling.
3. HTTP/transfers execute on workers; document saves/metadata execute on the GUI
   thread; nested event loops do not reenter the workflow generator.
4. Only authorized projects/items are returned before pagination; viewer roles
   do not get editable project choices. Invalid/inaccessible lookups are bounded
   and do not disclose inaccessible history.
5. A selected historical revision is retrieved with its original native geometry
   even after a newer revision exists.
6. Login/settings, local expiry, HTTP 401, malformed responses, connection
   refusal, timeout, cancellation and cleanup have automated coverage.
7. Backend and addon suites, lint/format, manifest validation and deterministic
   ZIP/import checks pass. Real FreeCAD evidence is distinguished from mocks.

Actual results are recorded in `docs/validation/freecad-phase2-2026-10-29.json`.
Final validation on Linux/FreeCAD 1.1.4/Python 3.11.14/Qt 6.8.3: **64 addon
tests passed**, **21 backend tests passed**, and **29 live MCP checks passed**.
Addon Ruff lint/format, manifest validation, deterministic ZIP and isolated
installed-import checks passed. The tested build was installed into both existing
FreeCAD profiles with backups. The normal backend was restarted, its metadata
counts were unchanged, and the restored user session successfully read Prototype
Project and item search from the new catalog endpoints. The isolated test servers
were stopped and generated credentials deleted. Acceptance criteria are met on
this tested runtime; the manual/platform limitations below remain explicit.

The live MCP harness executes all nine commands against an isolated backend,
fills the real login dialog automatically, observes GUI heartbeats and thread
IDs, selects human-readable projects, retrieves revision A after creating B,
and exercises expiry/timeout/cancellation. Slow HTTP fault injection is supplied
by a separate loopback test server; normal catalog/editing requests use the real
ForgePDM backend. User documents, identity and non-secret preferences are restored.

The live session retained old Python command callbacks after module reload.
For testing only, the harness rebound retained command instances before invoking
the registered IDs. Normal installations load callbacks at startup; restart
FreeCAD after installing 0.2.0. A full cold-start/platform matrix remains manual.
CI configuration is added locally; no GitHub workflow execution is claimed.

## Dependencies, risks and explicit limits

- Addon 0.2.0 requires the Phase 2 catalog endpoints. Old servers produce upgrade/
  restart guidance; existing write contracts remain compatible.
- Cancellation is cooperative and may wait until a blocked socket operation
  finishes or times out. It stops follow-up steps, not completed server changes.
  Finalization is non-cancellable. Upload/check-in remain separate operations.
- CAD saves/recompute remain synchronous, and working content is not yet isolated
  as an immutable local snapshot. Workspace/overwrite protection for editing is
  Phase 3; native-dataset selection remains newest by timestamp within the chosen
  explicit revision until dataset/configuration policies are implemented.
- Download publication requires filesystem hard-link support. Unsupported
  filesystems fail without replacing an existing destination.
- Search uses SQLite ASCII case folding; broader Unicode search is not claimed.
- External FreeCAD references are not repaired. Missing/inaccessible component
  datasets stop assembly opening, but having all files does not prove assembly
  correctness. Non-empty assembly reconstruction was not validated here.
- Public licensing, distribution and production hardening remain outstanding.

## Out of scope and next phase

No managed workspace, CAD reference rewriting, automatic BOM extraction, atomic
check-in, SSO, web UI, ERP connector, PostgreSQL migration, publication or external
repository is introduced. Phase 3 is recommended after user review of Phase 2;
it has not started. No commit/push is performed without explicit authorization.
