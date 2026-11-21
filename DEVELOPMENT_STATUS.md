# Development status

This is the current handoff. Start with [README](README.md) and
[Contributing](CONTRIBUTING.md). Earlier chronology and dated test counts live in
[history](docs/history/development-log.md); current rules live in the linked guides.

## Delivery

- Addon: **0.27.0**
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
- Frozen customizable TechDraw BOMs, format-1 direct/format-2 non-direct/format-3 localized/format-4 sorted/format-5 linked/format-6 automatic/format-7 stable-geometry tables,
  and explicit PDF publication pinned to exact uploaded source bytes. New drawing
  tables default to item-number sorting; configurable ascending/descending order
  preserves nested subtrees, positions, row notes and frozen source evidence.
- Native TechDraw balloons automatically resolve connected managed component geometry
  for ordinary/projection-group views, with explicit manual fallback, and link to frozen Direct BOM entries using existing
  BOM Positions. Table/balloon updates are atomic; unresolved targets require explicit
  relinking and block new ForgePDM PDF rendering. Leader placement/style are preserved.
  See [drawing workflow](docs/user/drawings.md#link-a-balloon-to-a-bom-entry) and
  [ADR-029](docs/decisions/ADR-029-linked-drawing-balloons.md).
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

2026-11-20 complete component insertion: addon **0.27.0** is installed in both
profiles and loaded in FreeCAD; the browser insertion callback is verified. It adds the browser's
**Insert into Assembly** action for exact uploaded P/A snapshots. A destination-owned
native link representation includes the source Assembly and external Fasteners as
one rigid occurrence, without moving source objects. Parent BOM/tree/balloon identity
resolves to the source assembly; member links retain exact CAD dependencies. Compatible
component replacement preserves member names and joint paths. Save/upload and BOM
review remain explicit. Backend **0.3.3** / schema **20** are unchanged. See
[workflow](docs/user/freecad.md#insert-components-from-the-browser) and
[ADR-032](docs/decisions/ADR-032-complete-rigid-component-insertion.md).

591 addon tests (seven optional Qt modules skipped), 39 real Qt tests and 19 isolated
native FreeCAD checks cover complete geometry/placements, repeated occurrences,
BOM identity, undo/redo, save/reopen, archive references, damaged representation
rejection, native grounded/fixed joints, replacement and rendered PDF output.
Native fixtures use a separate process/profile/X display and copied configuration;
no production upload/check-in/publication or engineering-document edits are performed.
Native FreeCAD logs include DAG/still-touched warnings around joint recomputation;
resolved joint paths and replacement rollback checks remain enforced. An isolated
fixture experiment deleting projected views crashed that test process; that sequence
was removed and the user's running FreeCAD was unaffected. Real HTTP transfer of a
new parent and flexible subassemblies remain outside this acceptance. Prior addon
profiles are retained in `var/backups/before-complete-component-insertion`.

2026-11-20 stable balloon evidence: addon **0.26.0** is installed in both profiles
and active in FreeCAD. New automatic bindings use version 3/profile
`occt-brep-q12-v1` and table format 7; formats 1–6 and the exact version-2 legacy
reader remain supported. Fingerprinting normalizes insignificant serialized real
values and kernel processing flags without changing native shapes. Geometry,
placement, topology, occurrence/revision membership, arrow/view and frozen BOM
identity checks remain. Unknown formats/profiles fail closed. Table updates and
manual linking preserve format 7. See [ADR-031](docs/decisions/ADR-031-stable-balloon-geometry-evidence.md).

577 addon tests (seven optional Qt modules skipped), 37 real Qt tests and 15 native
checks pass. Final native acceptance runs in a separate process, temporary profile
and X display, with no production login and only copied configuration files. It
uses the actual configuration/PDF loaders on this assembly's transformed parts
and Fasteners: all six component fingerprints survive BREP roundtrips, all seven
automatic links survive reconstruction/save/reopen and real arrow/placement/target
changes remain rejected. The generated PDF is visually checked. The PDF renderer
reported two nonfatal empty-closepath warnings from the native output; no visible
content loss was observed. Lint/format, documentation and packaging checks pass.

Under the user's explicit repair request and revalidated Working/edit/owned-live-
checkout guards, seven legacy automatic bindings in the working assembly were
rebaselined atomically to their verified existing targets. Non-geometry view/arrow
fields, component occurrence/revision sets, frozen entry identity and exact target
arrow hits were verified; there was no replacement guessing. All BOM Positions,
manual binding, table report/notes/SVG, text, leaders and styles are retained. The
saved working copy passes balloon and native-reference validation with zero issues;
component file bytes are unchanged. It still needs explicit Upload before Publish
Drawing PDFs. No server upload/check-in/publication was performed by this change.

FreeCAD exited during closure of owned native test copies in the initial shared-
session probe. Saved files, the live unsaved assembly and original addon profiles
had been backed up immediately beforehand. All three working documents were
reopened through recovery, and the user logged back in. Remaining native acceptance
was moved to the isolated process described above; the harness now rejects a normal
user profile, open documents, production login and non-temporary configurations.
Retain `var/backups/before-stable-balloon-fingerprints`, including the live snapshot,
recovery cache, original bindings and reconciliation evidence. See
[validation](docs/validation/stable-balloon-fingerprints-2026-11-20.json).

2026-11-20 automatic-balloon fingerprint investigation: the user's assembly's
seven format-2 automatic bindings fail in both the working document and an exact
source-pinned replay of the PDF configuration loader. All non-component evidence
(arrow/view/scale/orientation) and component revision IDs match. The local source
hash equals the workspace's recorded uploaded hash; there is no pending local PDF
publication journal. One manually linked balloon is unaffected.

The fingerprint hashes raw `exportBrepToString()` output for every component in a
view. Native probes demonstrate that serialization/reconstruction can change
insignificant numerical values and OCCT's transient Checked flag. Live versus
reconstructed component BREP strings differ, but all six match after diagnostic
normalization of that flag and numerical roundoff; observed vertex deltas are
below 7.2e-15 mm, and revision IDs/vertex counts match. An isolated evidence refresh
clears all seven errors and survives save/reopen. These findings expose unstable
representation-based evidence and view-wide invalidation; they do not prove an
arbitrary old hash is safe to replace. No validation relaxation, original balloon
relink, production save/upload or PDF publication was performed. Original saved
file bytes and recorded object properties are preserved.

This investigation led to the versioned correction recorded above. Its original
evidence and cautions about old one-way hashes remain valid; ordinary inspection
never upgrades bindings. See
[investigation evidence](docs/validation/balloon-fingerprint-investigation-2026-11-20.json).

2026-11-20 balloon problem highlighting: addon **0.25.0** is installed in both
profiles and active in FreeCAD. **Check BOM Balloons…** opens an offline, read-only
panel with numbered red bubble markers, exact-object selection, specific attachment
failure reasons and the existing guarded **Link selected…** workflow. The list
revalidates after edits/undo/relinking and supports explicit Recheck; closing it
removes its observer and markers. Correct frozen bindings are never adopted or
rewritten by inspection. Markers are viewport widgets, outside the native drawing
scene and PDF output. No backend/schema change. See
[user workflow](docs/user/drawings.md#find-balloons-that-need-repair).

543 addon tests (seven optional Qt modules skipped), 37 real Qt tests and eight
installed native checks pass. Native coverage includes ordinary/projection-group
positions, valid-balloon exclusion, selection, frozen/file preservation, repaired
entry removal and panel/document cleanup. Before/after native PDF rasterizations
are pixel-identical. The new command is registered in the current workbench; its
panel is open with eight markers on the recovered drawing. Lint, formatting,
documentation and packaging checks pass; no production upload/check-in/relink was
performed. See [validation](docs/validation/balloon-problem-highlights-2026-11-20.json).

During initial page-graphics inspection FreeCAD exited unexpectedly. The native
scene-item inspection/reopening sequence preceded the exit; its exact crash cause
was not established. The shipped implementation never inspects or wraps native
graphics items and tests viewport painting separately. The recovery cache and saved
assembly were backed up before restarting. FreeCAD reopened all three documents
through recovery; recovered unsaved state was retained, and the user subsequently
logged in again. Disk ZIP integrity checks pass, but no claim is made that edits
newer than the last recovery snapshot survived. Backups and local evidence are under
`var/backups/before-balloon-problem-highlights`; do not discard recovered edits.

2026-11-20 saved reference paths: addon **0.24.4** is installed in both profiles
and active in FreeCAD. Controlled saves inspect serialized component paths and
refresh only stale native link caches, including ordinary saves and writable Save
As. Correct paths and unresolved/genuinely different targets are not relinked;
strict transfer validation remains unchanged. 533 addon tests (six optional Qt
modules skipped), 16 installed native checks and the retained Upload/Check In
callbacks pass. Native coverage reproduces the FreeCAD 1.1.4 Save As defect for
App::Link and Assembly::AssemblyLink, repairs/reopens both and preserves internal
links, placements and component bytes. Documentation/lint/format/package checks
pass; no backend/schema change or production HTTP mutation was performed.

The user's backed-up assembly working copy now passes saved-reference and client
upload-preparation validation. Three open documents, the authenticated session,
component bytes, frozen table/balloon bindings and revision pins are preserved;
native recompute changed three placement coordinates only below 8e-31 mm. Three
balloons still fail PDF attachment validation (two have older view-scale evidence;
one has different geometry hashes). Their bindings were preserved, not automatically
reconciled. Relink them explicitly before PDF publication. No upload/check-in was
performed. Prior profiles, original working-copy bytes and detailed local evidence
are retained under `var/backups/before-saved-reference-path-fix`. See
[validation](docs/validation/saved-reference-paths-2026-11-20.json).

2026-11-20 concise balloon choices: addon **0.24.3** is installed in both profiles
and loaded in FreeCAD. The automatic component chooser omits the redundant CAD
occurrence label; item number, revision, BOM Position and description remain.
All 20 command workflow cases pass, including exact choice text and unchanged
selected-entry identity; lint/format, documentation and package checks pass.
The active prompt/workflow, all three open documents and authenticated session
were preserved during the live update. Already open prompts keep their original
contents; new prompts use the concise labels. Prior addon copies are retained
under `var/backups/before-concise-balloon-choices`. No backend/schema change.

2026-11-20 balloon choice descriptions: addon **0.24.2** is installed in both
profiles and active in FreeCAD. Overlapping-component choices now include the
frozen BOM description in its saved language, falling back to item name and then
“No description”. 519 addon tests (six optional Qt modules skipped), four repository
documentation tests and a native Qt chooser/selection check pass. Existing target
identities are retained; there are no server/schema or native document mutations.
All three open documents, unsaved edits, authenticated session and existing observer
are preserved. Prior addon copies are under `var/backups/before-balloon-choice-descriptions`.
See [validation](docs/validation/balloon-choice-descriptions-2026-11-20.json).

2026-11-20 projection-group balloon fix: addon **0.24.1** is installed in both
profiles and loaded in the current authenticated FreeCAD session. Grouped projected
sources now validate through their owning page's DrawProjGroup.Views; unrelated
pages/documents remain rejected. 516 addon tests (six optional Qt modules skipped),
four repository-documentation tests and six installed native checks pass, including
manual/automatic binding, table update, save/reopen, PDF preflight and rendering.
Both balloons in the user's actual drawing pass a read-only validation. All three
open documents retain file bytes, modified/touched/object states, labels and frozen
balloon/table metadata; the active document, selection and authenticated session are
preserved. No user document was saved or relinked. Backend/schema are unchanged;
all 44 database tables and 238 blob hashes match the verified backup. Prior addon
profiles and backup are under `var/backups/before-projection-balloon-fix`. See
[fix evidence](docs/validation/projection-group-balloon-fix-2026-11-20.json).

2026-11-20 automatic balloon attachments: addon **0.24.0** is installed in both
profiles and active in FreeCAD 1.1.4 / Qt 6.8.3 with its document observer enabled.
510 addon tests (six optional Qt modules skipped), 28 real Qt tests and four
repository-documentation tests pass. Eleven installed native checks cover picking,
actual TechDraw_Balloon creation, retargeting, undo/redo, bubble-only movement,
restoration exclusion, format-6 persistence/integrity and PDF rendering/preflight.
A native projection-group probe passes; the PDF is visually verified. Transport,
workspace and chooser answers are fixtures; no real-account HTTP publication or
production CAD mutation was performed. A redundant GUI save in acceptance was
removed because it opens the native dependent-files dialog; document API saves
and background-calculation settling retain persistence coverage.

Backend **0.3.3** / schema **20** are unchanged. The verified backup and prior
addon profiles are under `var/backups/before-automatic-balloons`. All 44 database
tables, 29 items, 33 revisions, 247 files and 238 blob hashes are unchanged. The
empty document/unauthenticated session state is restored. Automatic links follow
arrow movement and use existing Direct BOM Positions, version-2 attachment
metadata and table format 6. Overlaps require selection; specialized views retain
manual fallback. Existing restored balloons are never automatically adopted.
See [ADR-030](docs/decisions/ADR-030-automatic-balloon-attachments.md) and
[installed evidence](docs/validation/automatic-balloons-2026-11-20.json).

2026-11-19 linked drawing balloons: addon **0.23.0** is installed in both profiles
and loaded from the installed path in FreeCAD 1.1.4 / Qt 6.8.3. Backend **0.3.3**
and schema **20** are unchanged. 490 addon tests (six optional Qt modules skipped),
28 real Qt tests, four repository-documentation tests and 12 native checks pass.
Native acceptance covers explicit adoption, native expression text, retained leader/
style, multiple tables/balloons, atomic failure and undo/redo, managed FCStd integrity,
offline save/reopen, reconciliation/orphans and PDF output/export gating. The PDF
is visually checked. Export-gate acceptance uses a fixture configuration opener;
no HTTP publication or production drawing mutation was performed. Lint, formatting,
documentation and packaging checks pass. The new menu command and its actual
registered callback dispatch are verified without advancing the workflow.

A verified backup and prior addon installations are retained under
`var/backups/before-linked-balloons`. All 44 database tables, 29 items, 33 revisions,
247 file records and 238 blob hashes are unchanged. The original empty document
and unauthenticated session state and active workbench are preserved. Linked tables
use format 5; older addons reject their edits. Existing drawings/balloons are never
automatically adopted or rewritten. Direct links use the existing BOM Position;
renumber/replacement/changed duplicate sets require explicit relinking. See
[installed/native evidence](docs/validation/linked-balloons-2026-11-19.json).

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
- TechDraw tables are bounded to 500 rows and one page. Sheet splitting, Indented/Flattened balloon links, automatic placement/recognition,
  CAD-property mappings and stale-publication gates remain open.
- Broader supplier coverage, stock/cutting workflows and ERPNext synchronization
  remain separate increments. Remaining features have no agreed order.
- Advanced material records/APIs, migrations, old-file retrieval and local durable
  recovery journals remain supported compatibility surfaces. Preserve them.

Native acceptance uses Linux FreeCAD 1.1.4 / Python 3.11.14 / Qt 6.8.3. Other
platform/runtime combinations are unverified. Never infer present documents,
sessions or checkout state from earlier evidence. Follow the
[roadmap](docs/development/roadmap.md), [release guide](docs/development/releasing.md)
and [test tiers](docs/development/testing.md); preserve documents and engineering data.
