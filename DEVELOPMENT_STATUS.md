# Development status

This is the current handoff. Start with [README](README.md) and
[Contributing](CONTRIBUTING.md). Earlier chronology and dated test counts live in
[history](docs/history/development-log.md); current rules live in the linked guides.

## Delivery

- Addon: **0.20.1**
- Backend package: **0.1.2**
- Database schema: **18**

Versions are independent. The backend/server is AGPL-3.0-or-later and the
Workbench LGPL-2.1-or-later; approved licensing/contact boundaries remain unchanged.
An installable Addon Manager distribution source/publication is still separate.

## Current behavior

- FastAPI/SQLite metadata, separate immutable SHA-256 bytes, bearer sessions,
  project/shared-library permissions, permanent P/A/S/M codes and audit history.
- Exact revisions and managed FreeCAD dependency manifests/workspaces; exclusive
  fenced checkout/check-in, lifecycle and recoverable native revision creation.
- Shared S/M catalog, Fasteners association, descriptions, physical material
  snapshots, P/S mass evidence and revision-pinned assembly mass.
- Persistent FreeCAD browser with Recent/Favorites/My Checkouts; web browsing,
  description controls and account/project administration.
- Direct/Indented/Flattened BOM reports shared across clients. CAD-to-BOM changes
  remain explicit reviewed direct replacements; quantities/exact pins are retained.
- Frozen customizable TechDraw BOMs, format-1 direct/format-2 non-direct tables,
  and explicit PDF publication pinned to exact uploaded source bytes.
- Shared 384px isometric previews for new native uploads/check-ins. Each image is
  an immutable derivative of one exact source file; selected-snapshot images appear
  in FreeCAD and web. Capture preserves view/document state, rejects unsaved linked
  geometry and never backfills existing files automatically. Optional image failure
  does not undo CAD success. See [previews](docs/user/freecad.md#snapshot-previews)
  and [ADR-025](docs/decisions/ADR-025-immutable-isometric-thumbnails.md).
- Online SQLite/blob backups, full hash/FK/schema verification, new-directory
  restore, isolated drills and hourly/daily Linux user timers. Status exposes
  missing/failed/interrupted/stale runs. Known older schema backups remain readable.

## Validation and local installation

2026-11-16: 301 backend tests, 422 addon tests (four optional Qt modules skipped in
base), 21 real Qt checks and 21 Node checks pass. Lint/format, canonical docs,
manifest/archive links and backend wheel/sdist checks pass. Installed FreeCAD
acceptance passes 28 atomic/recovery and 13 thumbnail/render/browser checks;
real Chrome passes 10 preview and 26 general browsing checks. All mutation fixtures
are disposable. Camera restoration also covers perspective and render failure.

Addon 0.20.1 is installed in both local profiles and loaded in FreeCAD 1.1.4;
backend 0.1.2 runs on loopback with schema 18. A verified schema-17 backup and prior
addons are retained under `var/backups/before-thumbnails`. The migration preserves
all prior records (only adds schema row 18) and all 217 physical file hashes;
existing CAD receives no automatic preview. Current scheduled backup/drill runs
pass at schema 18, and schema-17 archives still verify. A separate restored
fixture verifies 16 thumbnail associations and all 32 source/image file records.
The 0.20.1 patch resolves retained pre-update native command instances before
workflow execution. A read-only actual-button probe verifies current Upload and
Check In routing and preserves four open documents/session. Existing missing
previews are not backfilled. See
[handler-fix evidence](docs/validation/thumbnail-checkin-handler-2026-11-16.json).
See [installed evidence](docs/validation/thumbnails-installed-2026-11-16.json),
[native evidence](docs/validation/thumbnails-native-2026-11-16.json) and the
[validation index](docs/validation/README.md).

Backups use `var/backups/automated`; scratch restores use `var/restore-drills`.
The hourly backup and daily 03:15 drill user timers remain enabled. See
[operations](docs/operations/backups.md). Previous cleanup and backup acceptance,
including data preservation and earlier Qt/browser counts, remains in dated
[history](docs/history/development-log.md) and the validation index.

## Current limits and next priorities

- Backup storage is on the same local drive. Off-device copies, retention, alerts,
  workstation/unsaved-edit backup and full disaster cutover remain open. No backup
  generation is automatically pruned; timers require an active user systemd manager.
- Production security, controlled GC and wider multiuser/platform/clean-start
  acceptance remain open. Future GC must coordinate with active backup readers.
- Thumbnails have no automatic backfill, per-row lazy loading, headless service or
  sheet-preview rendering. Capture caps individual files at 256 MiB and linked
  documents at 1000; missing/unavailable images never prevent opening CAD.
- TechDraw tables are bounded to 500 rows and one page. Sheet splitting, balloons,
  CAD-property mappings and stale-publication gates remain open.
- Broader supplier coverage, stock/cutting workflows and ERPNext synchronization
  remain separate increments. No next feature order is assumed.
- Advanced material records/APIs, migrations, old-file retrieval and local durable
  recovery journals remain supported compatibility surfaces. Preserve them.

Native acceptance uses Linux FreeCAD 1.1.4 / Python 3.11.14 / Qt 6.8.3. Other
platform/runtime combinations are unverified. Never infer present documents,
sessions or checkout state from earlier evidence. Follow the
[roadmap](docs/development/roadmap.md), [release guide](docs/development/releasing.md)
and [test tiers](docs/development/testing.md); preserve documents and engineering data.
