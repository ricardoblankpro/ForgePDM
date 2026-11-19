# Development status

This is the current handoff. Start with [README](README.md) and
[Contributing](CONTRIBUTING.md). Earlier chronology and dated test counts live in
[history](docs/history/development-log.md); current rules live in the linked guides.

## Delivery

- Addon: **0.22.2**
- Backend package: **0.3.3**
- Database schema: **20**

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
  Fasteners pt-BR proposals now cover all 99 mapped standards (4 types/23 families),
  62 controlled materials and 37 finishes through a separately versioned local
  vocabulary. Family names do not infer nylon, tip shape or serrations; unknown
  material/finish text is preserved with draft warnings. See
  [terminology and remaining limits](docs/development/references/fastener-pt-BR.md).
- The web translation tab compares original and target descriptions, keeps the editing
  language separate from catalog display, shows saved/unsaved/review/approval states,
  and offers specification/material assistance only when available. Original language
  settings and history are secondary controls. Unsaved session buffers survive
  navigation and conflicts; approvals update the header/catalog immediately.
- One canonical description/translation editor per revision: assigned material or manual P text, manual A, fixed structured S or manual generic S, and revisioned M text. Legacy item text remains available as history. See [ADR-027](docs/decisions/ADR-027-single-revision-description.md).
- Shared S/M catalog, Fasteners association, descriptions, physical material
  snapshots, P/S mass evidence and revision-pinned assembly mass.
- Native tree descriptions follow the browser/BOM language, including exact associated
  Fasteners S revisions. Full-text hover tooltips and local geometry/label fallback
  preserve assembly checkout ownership and unsaved description edits.
- Persistent FreeCAD browser with Recent/Favorites/My Checkouts; web browsing,
  description controls and account/project administration.
- Direct/Indented/Flattened BOM reports shared across clients. CAD-to-BOM changes
  remain explicit reviewed direct replacements; quantities/exact pins are retained.
- Frozen customizable TechDraw BOMs, format-1 direct/format-2 non-direct/format-3 localized/format-4 sorted tables,
  and explicit PDF publication pinned to exact uploaded source bytes. New drawing
  tables default to item-number sorting; configurable ascending/descending order
  preserves nested subtrees, positions, row notes and frozen source evidence.
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

2026-11-18 drawing BOM sorting: addon **0.22.2** is installed in both profiles
and active in FreeCAD 1.1.4 / Qt 6.8.3. Backend **0.3.3** and schema **20** are
unchanged. 456 addon tests (five optional Qt modules skipped), 25 real Qt tests,
and nine native TechDraw/UI/save-reopen/PDF checks pass. The exported PDF is
visually checked for sorted rows and matching notes. Lint, formatting, documentation
and packaging checks pass. A verified backup and prior addon copies are retained
under `var/backups/before-drawing-bom-sort`. All database tables, 29 items,
33 revisions, 245 file records and 237 blob hashes are unchanged. Three open
documents retain their file bytes, paths, modified/touched flags, object labels,
Fasteners associations and frozen table data; active document and authenticated
session are preserved. Existing tables are not automatically rewritten; older
layouts default to stored order and explicitly sorted updates use format 4. See
[sorting evidence](docs/validation/drawing-bom-sort-2026-11-18.json) and
[ADR-028](docs/decisions/ADR-028-drawing-bom-sort-order.md).

2026-11-18 native tree descriptions: backend **0.3.3** / schema **20** runs
on loopback; addon **0.22.1** is installed in both profiles and active in FreeCAD
1.1.4 / Qt 6.8.3. 556 backend, 433 addon (five optional Qt modules skipped),
23 real Qt and nine native Fasteners/browser/BOM/hover checks pass. Native
acceptance uses disposable data; a read-only production probe verifies all three
open screw/washer/nut rows in Portuguese with full tooltips. Lint, formatting,
documentation and packaging checks pass. A verified backup and prior addon copies
are retained under `var/backups/before-tree-descriptions`. Engineering tables,
29 items, 33 revisions, 245 file records and 237 blob hashes are preserved;
a concurrent source-language confirmation is retained. Three open documents keep
their file bytes, object labels/associations, paths and modified/touched flags;
the active document, column layout and authenticated session are preserved.
No production translations were created by acceptance. See
[native tree and installation evidence](docs/validation/tree-descriptions-2026-11-18.json).

2026-11-18 translation editor: backend **0.3.2** runs on loopback with schema
**20**; addon **0.22.0** remains installed. 554 backend tests, 23 Node tests,
34 translation-editor Chrome checks and 13 unified-description Chrome regressions
pass. Lint, formatting, documentation links, backend wheel/sdist, isolated wheel
resources and addon documentation packaging pass. A fresh verified backup is
retained under `var/backups/before-translation-editor`. All database tables,
29 items, 33 revisions, 243 file records and 236 unique blob hashes are preserved.
Three open FreeCAD documents retain their paths, hashes and modified flags;
the active document and authenticated session are unchanged. No production
translations were created. See [editor and installation evidence](docs/validation/translation-editor-2026-11-18.json).

2026-11-18 unified descriptions: backend **0.3.0** / schema **20** runs on
loopback; addon **0.22.0** is installed and verified in both profiles and loaded
in FreeCAD 1.1.4. 550 backend, 426 addon (five optional modules skipped), 23 real Qt,
21 Node, 11 localization Chrome and 13 unified-description Chrome checks pass.
Native acceptance verifies an installed HTTP client and real P description
save/reopen using disposable data. No document/session was open before acceptance;
that state was preserved. Lint, formatting, documentation and packaging checks pass.

A verified schema-19 backup and addon copies are retained under
`var/backups/before-unified-description`. Isolated and installed migration checks
preserve all original engineering tables, localization history, 27 items,
31 revisions, 229 file records and 225 unique blob hashes. All blob hashes,
SQLite integrity and foreign keys verify. Historical shared text backfill records
its origin; stale CAD copies may need explicit description reconciliation.
Existing native files, frozen tables and PDFs are untouched. See
[installed/migration evidence](docs/validation/unified-descriptions-2026-11-18.json).

2026-11-18 Fasteners proposal increment: 543 backend tests pass, including 242
localization cases and per-standard pt-BR/English contract checks. All 297 English
proposals recorded before the change remain identical. Backend/tooling lint,
format, documentation links and an isolated wheel import/generation pass. The
shared standard map, schema and review service are unchanged; old provenance and
approved text are regression-tested. No production translations were created. See
[coverage evidence](docs/validation/fastener-pt-BR-2026-11-18.json).

2026-11-16 localization: 312 backend tests, 426 addon tests (five optional Qt
modules skipped), 23 real Qt checks, and 21 Node checks pass. Real Chrome passes
26 general browsing and 11 localization checks. Installed native acceptance
checks Portuguese creation/English approval, search, unchanged CAD-description
tokens, localized BOM provenance and real format-3 TechDraw save/reopen. Original
four document paths/hashes/dirty states and the authenticated session are retained.

On 2026-11-16 addon 0.21.0 was installed in both profiles and loaded in FreeCAD 1.1.4;
backend 0.2.0 ran on loopback with schema 19. A schema-18 backup is retained under
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
