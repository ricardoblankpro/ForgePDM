# Development status

This is the current handoff. Start with [README](README.md) and
[Contributing](CONTRIBUTING.md). Earlier chronology and dated test counts live in
[history](docs/history/development-log.md); current rules live in the linked guides.

## Delivery

- Addon: **0.21.0**
- Backend package: **0.2.0**
- Database schema: **19**

Versions are independent. The backend/server is AGPL-3.0-or-later and the
Workbench LGPL-2.1-or-later; approved licensing/contact boundaries remain unchanged.
An installable Addon Manager distribution source/publication is still separate.

## Current behavior

- FastAPI/SQLite metadata, separate immutable SHA-256 bytes, bearer sessions,
  project/shared-library permissions, permanent P/A/S/M codes and audit history.
- Exact revisions and managed FreeCAD dependency manifests/workspaces; exclusive
  fenced checkout/check-in, lifecycle and recoverable native revision creation.
- Reviewed en/pt-BR description localization with source history, original fallback,
  Unicode search, local fastener proposals and separate translation approval. Legacy
  originals remain `und` until confirmed. See [languages](docs/user/localization.md).
- Shared S/M catalog, Fasteners association, descriptions, physical material
  snapshots, P/S mass evidence and revision-pinned assembly mass.
- Persistent FreeCAD browser with Recent/Favorites/My Checkouts; web browsing,
  description controls and account/project administration.
- Direct/Indented/Flattened BOM reports shared across clients. CAD-to-BOM changes
  remain explicit reviewed direct replacements; quantities/exact pins are retained.
- Frozen customizable TechDraw BOMs, format-1 direct/format-2 non-direct/format-3 localized tables,
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

2026-11-16 localization: 312 backend tests, 426 addon tests (five optional Qt
modules skipped), 23 real Qt checks, and 21 Node checks pass. Real Chrome passes
26 general browsing and 11 localization checks. Installed native acceptance
checks Portuguese creation/English approval, search, unchanged CAD-description
tokens, localized BOM provenance and real format-3 TechDraw save/reopen. Original
four document paths/hashes/dirty states and the authenticated session are retained.

Addon 0.21.0 is installed in both local profiles and loaded in FreeCAD 1.1.4;
backend 0.2.0 runs on loopback with schema 19. A schema-18 backup is retained under
`var/backups/before-localization`, with an additional immediate deployment backup
and prior addon profiles. Migration rehearsal and installed comparison preserve
all 39 original tables/columns, 26 items, 30 revisions, 221 file records and 220
unique blob hashes. Only language metadata/source history and schema version are
added; all real legacy languages remain `und`. No production translations were
created by acceptance. Schema-19 backup and isolated restore drill pass; prior
schema-18 archives still verify. See [migration evidence](docs/validation/localization-migration-2026-11-16.json),
[installed evidence](docs/validation/localization-installed-2026-11-16.json),
[native evidence](docs/validation/localization-native-2026-11-16.json),
[Chrome evidence](docs/validation/localization-web-2026-11-16.json) and
[ADR-026](docs/decisions/ADR-026-versioned-item-description-localization.md).
Earlier thumbnail/recovery evidence remains in the [validation index](docs/validation/README.md).

Backups use `var/backups/automated`; scratch restores use `var/restore-drills`.
The hourly backup and daily 03:15 drill user timers remain enabled. See
[operations](docs/operations/backups.md). Previous cleanup and backup acceptance,
including data preservation and earlier Qt/browser counts, remains in dated
[history](docs/history/development-log.md) and the validation index.

## Current limits and next priorities

- Localization covers descriptions, with en/pt-BR shipped choices. No interface
  translation, automatic language detection, bulk legacy classification, external
  provider or source promotion is included. Self-approval is permitted; larger
  catalogs may need indexed search. Refresh open presentations after approval.

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
