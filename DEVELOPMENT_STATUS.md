# Development status

## 2026-11-05 — Specification selections and uppercase catalog text (0.7.3)

- Fasteners-driven registration now uses one form with controlled material,
  mechanical-class and finish choices; known norms classify type/family, unknown
  norms require explicit choices. Extended options include researched specialist
  entries. Obvious family/material mismatches are filtered; no certification of
  every product/size/coating combination is implied.
- Generate Name and Description as TYPE MATERIAL FAMILY NORM DIMENSION GRADE
  FINISH, uppercase with X dimensions, and show a live preview. No separate name/
  description prompts for this path. Preserve unknown values, custom dimensions
  and left-hand indication; reject oversized names without silent truncation.
- Existing S items/associations and backend specification contract remain intact;
  no migration or automatic alias merge. Generic purchased-item registration
  without Fasteners geometry retains manual text entry.
- Validation: 337 addon tests, focused lint and 28 real Qt/HTTP checks passed on
  disposable data, including exact screw/nut/washer names, dependent choices and
  cancel safety. User document states and hashes preserved. Evidence:
  docs/validation/standard-parts-form-2026-11-05.json.
- Built and installed 0.7.3 in both local addon profiles with backups; runtime
  command dispatch refreshed. No engineering records automatically altered.

## 2026-11-05 — Specification dropdown vocabulary research (no implementation)

- User prefers specification-only registration with selections instead of free
  typing. Researched primary standards/manufacturer sources for a broad material,
  mechanical-class and finish seed inventory; see docs/fastener-selection-options-research.md.
- Recommend dependent family/material/class selectors and generated catalog text.
  Distinguish current vs legacy classes (notably ISO 898-2:2022), bolt vs nut vs
  washer/set-screw systems, and coating processes vs appearance. Unknown values
  and supplier extensions need explicit handling.
- Research is not an exhaustive certified compatibility matrix; extended stainless
  combinations and specialist specifications need further verification. No UI,
  schema, installed-addon or engineering-record changes in this research increment.

## 2026-11-05 — Selected standard-part reassociation (addon 0.7.2)

- Add Change Standard Part Association command for selected direct fasteners in
  an owned Working assembly. Reuse matching/registration for a different grade,
  material or finish; preserve occurrence UUIDs, placement, attachments and all
  unselected associations. Recheck edit/checkout rights before one undoable local
  transaction. Save/upload and reviewed BOM synchronization remain explicit.
- Shared upload preflight additionally detects association changes during review.
  No description/name standardization implemented; existing text remains unchanged.
- Validation: 321 addon tests passed; focused lint and package/layout checks passed.
  Focused tests cover subset changes, cancellation, stale metadata,
  checkout loss, invalid selection and new-spec registration. Disposable live
  CAD/HTTP checks prove two identical screws retain distinct grade 8.8/10.9
  revisions after upload/retrieval, with separate BOM quantities and preserved
  user documents/session. Eleven live checks passed. Built and installed 0.7.2
  in both addon profiles with backups; registered the new command in the current
  session. See docs/validation/standard-parts-reassociation-2026-11-05.json.

## 2026-11-05 — Repair stale GUI command instances after addon reload

- User upload skipped Fasteners prompts because FreeCAD retained the registered
  0.6.6 UploadCommand instance, despite the module being reloaded from 0.7.1.
  Re-adding an existing command name did not replace its Python instance.
- Rebound registered workflow command instances to the current installed classes.
  Intercepted dispatch without advancing workflows and verified both toolbar
  Upload and Check In now invoke actions containing the Fasteners preflight.
  No CAD save/upload or catalog mutation performed.
- Future in-process upgrades must verify registered command dispatch, not merely
  module version or command-name presence. A normal FreeCAD restart loads current
  installed classes without this hot-reload issue.

## 2026-11-05 — Qualified local Fasteners attachments (addon 0.7.1)

- Actual A000003 inspection found a valid local Assembly attachment using
  Body002.Hole.Edge5. The 0.7.0 adapter incorrectly required an unqualified name.
  Accept bounded local object paths ending in one topology element, resolve the
  full path and retain null-shape rejection. External attachment limits unchanged.
- Validation: 314 addon tests passed; disposable live save/reopen/path-rewrite
  checks passed, preserving all user document dirty/touched flags and saved hashes.
  Actual A000003 attachment passes read-only preflight; no user document saved,
  altered or uploaded. P000008 already had unsaved edits and was preserved.
- Built 0.7.1, updated both installed addon profiles with backups and reloaded the
  runtime adapter. No backend or schema change. Evidence:
  docs/validation/fasteners-qualified-attachment-2026-11-05.json.

## 2026-11-05 — Installed addon upgraded for user testing

- Installed 0.7.0 in both local FreeCAD addon profiles, preserving prior addon
  directories in the private ForgePDM-backups directory outside Mod. Verified
  every installed distribution file against the built ZIP.
- Reloaded installed modules and refreshed the running ForgePDM menu/toolbar;
  Register Standard / Purchased Part is available. No engineering document edits.
- Local database was already at migration 11; no new migration was needed. Started
  the configured loopback backend and verified health and standard-parts API presence.
  User can log in and test the workflow documented in docs/standard-parts.md.

## 2026-11-05 — Standard parts and Fasteners integration (addon 0.7.0)

- Complete S creation/search foundation plus metadata-only registration and explicit
  check-in/release actions. Migrations 10–11 preserve P/A counters, identifiers and
  relationships; S remains ordinary part kind with existing revision/access rules.
- Upload and Check In discover Fasteners, reuse exact associations, group new/changed
  specifications for confirmation, and offer registration of missing S items.
  Material/grade/finish are explicit, including unknowns. Normal toolbar-created
  root fasteners and direct native Assembly members are supported; nested local
  groups remain rejected. No automatic release or server BOM change.
- Save occurrence UUIDs, geometry and generator provenance in native snapshots.
  Validate/publish immutable occurrence evidence with datasets and atomic check-in.
  Extend reviewed BOM capture to mixed links/embedded fasteners without flattening
  linked subassemblies. Preserve manual-line review and stale/checkout guards.
- Narrow freecad-fasteners-v1 manifests pin external BaseObject targets and one
  explicit subelement. Retrieval rewrites paths before open, verifies attachments
  and associations, and rejects missing/null subelement shapes. Old link-only
  snapshots remain compatible. Compatible Fasteners installation is required.
- Validation: 140 backend tests, 305 addon tests, three web model tests; focused
  lint, web syntax and addon manifest/layout checks passed. Backend distributions
  and ForgePDM-0.7.0.zip built. Isolated real FreeCAD/HTTP pilot passed 32 checks:
  four families, managed attachments, qty eight, purchased-model qty two, atomic
  check-in/recovery, exact retrieval, edits/copies/deletion/cancel, stale reviews
  and nested assembly boundaries. Runtime: Linux FreeCAD 1.1.4 / Fasteners 0.5.43.
- Evidence: [live report](docs/validation/standard-parts-freecad-2026-11-05.json).
  Reusable isolated fixtures live under clients/freecad/tools/validation/.
  [Usage and limits](docs/standard-parts.md); architectural contract: ADR-010.
- No production database upgrade or installed-addon deployment in this session.
  Backend and addon must be upgraded together before using this with engineering
  data. Other families sharing the parameter contract can be discovered but are
  not individually certified; arrays, arbitrary proxies and semantic topology
  remapping remain unsupported. Phase 5 legacy-write/revision-retry debt remains.

## 2026-11-05 — S numbering backend foundation (partial implementation)

- Migration 10 adds item numbering series and independent P/A/S counters copied
  from previous counter values. Item creation accepts optional number_series;
  defaults remain P/A and assembly/S is rejected. Item API responses expose series.
- Validation: 131 backend tests passed; git diff --check passed. No live database
  upgrade or FreeCAD deployment performed.
- Remaining: catalog filtering and creation UI, stronger migration/concurrency
  coverage, metadata-only registration, matching and the complete Fasteners
  upload/check-in/BOM/retrieval integration. This is not a completed feature.

## 2026-11-05 — Simplified standard parts proposal (planning only)

- Reformulated the catalog proposal around the original Fasteners BOM problem:
  ordinary S-numbered parts, explicit multi-object association, and reviewed
  occurrence counting for one validated Fasteners case. Purchased models reuse
  existing managed links. Revisions, lifecycle and permissions stay in place.
- Authoritative proposal: [standard parts plan](ForgePDM_Standard_Parts_Implementation_Plan.md).
  The older catalog plan now links there. Automatic matching, taxonomy and special
  administration are deferred; duplicate-equivalence review is initially manual.
- First implementation task, when requested: reproduce attachment/capture/upload/
  retrieval behavior in disposable fixtures. No implementation or runtime changes;
  validation in this session is documentation/diff review only. Phase 5 debt remains.

## 2026-11-04 — Next priority: personal component catalog (planning only)

- User selected a ForgePDM-owned standard/purchased component catalog as the next
  feature, with optional Fasteners Workbench integration after the foundation.
- Detailed implementation sequence and acceptance gates:
  [component catalog plan](docs/component-catalog-plan.md). Reuse existing Items,
  revisions and exact BOM/reference workflows; separate catalog classification
  from part/assembly kind. Define specification identity, revision ownership,
  normalized matching and sharing permissions before implementation.
- Three increments: backend catalog and matching; browsing/managed CAD reuse;
  optional Fasteners adapter. No implementation, migration or runtime change in
  this session. Validation is documentation/diff review only.
- This is the next feature priority. Phase 5 reliability work remains pending;
  it has not been completed or removed from the roadmap.

## 2026-11-03 — Published TechDraw PDFs (addon 0.6.6)

- Add explicit Publish Drawing PDFs from clean uploaded managed Working copies
  with an owned checkout. Render selected pages from isolated verified exact
  configurations under a modal GUI guard; preserve original documents/selection
  and lease. One PDF per page, 1–32 pages, 25 MiB/page and 100 MiB/publication.
- Migration 9 adds immutable publications and page/source associations. Bounded
  ZIP transport, verified hashes, final lease/permission/source fencing and one
  metadata transaction protect the complete page set. Actor-scoped operation
  replay plus frozen local PDFs/journal recover response loss without reexport.
- Web Drawings tab provides publication/page history, exact native source details,
  stale same-revision warnings, authenticated download and native browser PDF
  preview. Temporary Blob URLs are revoked on navigation/session changes; tokens
  never enter URLs. Download fallback covers browsers without inline PDF support.
- Validation: 130 backend tests, 295 addon tests, three web model tests; live
  FreeCAD 1.1.4 fixture passed 59 checks; real Chrome drawings passed 18 checks,
  existing web/management acceptance passed 26/23. Evidence:
  docs/validation/drawing-pdfs-*-2026-11-03.json. No real engineering publication.
- Publication remains separate from native check-in and keeps the checkout.
  Subsequent native datasets can make published PDFs historical, including when
  bytes are unchanged. Released revisions remain read-only; new revisions start
  with their own publication list. Combined PDFs, automatic check-in integration,
  local cache cleanup and orphan-blob recovery remain deferred.
- Usage, architecture and limits: docs/drawing-pdfs.md and ADR-009.
- Deployment: backend wheel/addon ZIP and focused lint passed. Local migration 9
  applied after a private consistent database backup; hashes/counts of every
  existing non-migration table were unchanged and foreign-key checks passed.
  Both installed addon profiles updated with backups, and the new runtime command
  registered while preserving login, open document states, saved bytes and
  selection. Refresh the web page to load the new Drawings tab.

## 2026-11-03 — Embedded TechDraw pages (addon 0.6.5)

- Upload/check-in accepts native TechDraw SVG Template paths only when the same
  object has a verified embedded self-contained PageResult SVG. Preserve embedded
  bytes, editable fields, views, dimensions and notes; reconstruction uses FreeCAD's
  embedded template without reassigning Template or requiring its historical path.
  Other file/path assets and cross-document drawing adapters remain unsupported.
- Validate SVG/member limits, structure, local resource references and embedded
  PNG/JPEG images (including wrapped Base64). Reject missing/unsafe resources,
  external CSS/images, DTD/entities and active content. The user's saved drawing
  also passed read-only preflight with the new adapter; no automatic upload made.
- Settle native Qt drawing projection/face results before managed saves and
  reconstruction saves, with a bounded responsive wait. TechDraw documentation
  objects do not enter BOM quantities, including pages inside native Assembly.
  Local CAD validation failures now say that the failed step did not upload the
  snapshot; earlier completed writes and uncertain transport failures remain clear.
- Validation: 288 addon tests, focused lint and manifest/package checks passed.
  Real FreeCAD 1.1.4/HTTP disposable fixture passed 43 checks: two-page part and
  native assembly, atomic check-in, original SVGs unavailable, editable title
  re-check-in, 100 mm dimensions, notes/embedded logos/rendering, clean retrieval
  and exact child pins. User documents/dirty states/saved bytes preserved.
  Evidence: docs/validation/freecad-techdraw-2026-11-03.json.
- Both installed profiles updated with backups and running CAD/validation/command
  modules reloaded. Session and document states preserved; actual engineering
  check-in remains the user's explicit next action.
- Usage/scope: docs/techdraw-support.md. Pages share model revisions/checkouts;
  no backend schema/API changes, separate drawing revisions or PDF publication.

## 2026-11-03 — Visual tree status (addon 0.6.4)

- **Refresh PDM Status** adds an ephemeral native-tree PDM column beside labels.
  Independent colored badges/text/tooltips show your/other-user checkout and owner,
  released lifecycle, newer revision, and newer same-revision snapshot per exact
  occurrence pin. Include local-edit/unknown/stale indicators and refresh times.
  Native icons/error display, labels, properties, CAD dirty state and files remain
  unchanged. Duplicate indistinguishable document roots remain unknown safely;
  their occurrences in an identifiable parent still compare independent pins.
- Additive authorized `POST /api/v1/status/revisions` batches 1–200 revision IDs,
  reads a consistent metadata snapshot, hides missing/inaccessible identities
  identically and exposes only checkout owners of readable revisions. No migration
  or engineering rule changes. Latest snapshot ordering matches update commands.
- After explicit activation, refresh every 60 seconds and after PDM command
  completion. All HTTP/hash work runs in a worker; unchanged files reuse stat-keyed
  hash cache. Defer during commands/modals. Logout/account switch clears private
  statuses immediately; discard late previous-session replies. Offline/old data is
  explicitly stale. Status never grants edit permission or adopts server changes.
- Validation: 103 backend tests, 260 addon tests, focused lint, manifest validation,
  addon ZIP and backend wheel builds passed. Real FreeCAD 1.1.4/Qt 6.8.3 isolated
  two-user HTTP/Qt workflow passed 45 checks, including selected component pins,
  simultaneous status badges, owner names, offline recovery, logout/session races,
  command deferral and preserved CAD labels/properties/dirty flags/bytes/selection.
  Screenshot inspected locally; evidence: docs/validation/freecad-tree-status-2026-11-03.json.
- Both installed profiles updated with backups. Local backend gracefully restarted
  with original arguments/environment/data to load the new route. Runtime command
  registered and feature activated while preserving login and open documents.
  Usage/legend and adapter limitations: docs/tree-pdm-status.md. No startup network;
  after a future FreeCAD restart, use Refresh PDM Status to activate polling again.

## 2026-11-03 — Selected component snapshot updates (addon 0.6.3)

- New **Update Selected Components from Server…** command adopts the latest
  uploaded same-revision snapshot for reviewed direct occurrences of one source
  item/revision group at a time. Require a clean uploaded managed Working parent
  and owned checkout. Skip current occurrences; no automatic new-revision adoption.
- Extend the existing replacement transaction with explicit exact snapshot pins;
  recheck parent bytes/identity, pending recovery, source pins and checkout before
  applying. Preserve occurrence UUIDs, labels, placements, unselected targets and
  valid joints. Reject unsafe mappings/dependencies and rollback detected errors.
  Leave the parent modified; check-in and BOM synchronization remain explicit.
- Validation: 251 addon tests, focused lint and manifest/build checks passed.
  Live FreeCAD 1.1.4 with disposable HTTP DB/storage and two users passed 22 checks,
  including selected-only geometry adoption, preserved grounding/occurrences,
  cancellation, checkout enforcement, unchanged source/parent saved bytes and BOM,
  and mixed exact pins persisted by later atomic check-in. Native AssemblyLink
  same-revision replacement and generated-child constraint rollback also passed.
  User documents, saved hashes and session preserved. Evidence:
  docs/validation/freecad-component-update-2026-11-03.json.
- Both installed profiles updated with backups. Registered/enabled the command
  in the running ForgePDM menu and Updates toolbar; preserved login and active
  document. Future startup includes both update commands in the main toolbar.
- Workflow: docs/update-from-server.md. One group per operation; save/upload after
  inspecting it before updating another group. No geometry merge or schema/API
  changes. Phase 5 reliability follow-ups remain separate.

## 2026-11-03 — Update from Server (addon 0.6.2)

- Added explicit menu/toolbar command to compare the active managed document
  with the latest native upload on the same revision. Review timestamp/hash,
  retrieve the exact chosen snapshot, and activate a separate verified copy.
  Preserve the original document/files, incoming links and checkout state.
- Reject unsaved or saved-but-unuploaded edits, inconsistent workspace identity
  and pending check-in recovery. Recheck local state after download. Report
  newer revision labels without automatic adoption. Assembly roots retain their
  exact uploaded dependency manifest; component updates inside an existing parent
  remain a later increment. No backend/schema or PDM-rule changes.
- Validation: 238 addon tests passed. Focused lint and manifest/distribution
  checks passed. Real FreeCAD 1.1.4 with disposable HTTP storage, two users and
  separate workspaces passed 16 checks: changed geometry from another user's
  check-in, cancellation, clean verified copy, exact ledger, no new checkout or
  dataset, unsaved-edit rejection, worker HTTP, preserved user documents/bytes.
  Evidence: docs/validation/freecad-server-update-2026-11-03.json.
- Both installed addon profiles updated with backups. Command registered in the
  running FreeCAD menu and an Updates toolbar; enabled state and preserved login
  verified. Normal future startup includes it in the main ForgePDM toolbar.
- Usage and bounded design: docs/update-from-server.md. The original copy stays
  open deliberately; close it when no longer needed. Acquire checkout on the
  updated copy before editing. No geometry merging or automatic link retargeting.

## 2026-11-02 — Functional web management workspace

- User-approved GUI priorities brought forward: admin user creation/edit/enable/
  disable/roles, password resets and own-password changes, project properties
  (customer, due date, description), membership/roles, My checkouts and activity.
- Additive migration 8 preserves existing accounts/passwords/projects/leases.
  Consistent private local metadata backup taken before applying it. New/reset
  accounts must change their temporary password before other API access; existing
  accounts are unchanged. Password changes/reset/disable/role changes revoke
  sessions. Current admin role is checked inside writes; last-admin removal and
  unsafe self-disable/demotion are rejected. No password/token data is audited.
- Regular users see assigned project properties, their accessible unreleased
  checkouts and scoped activity. Activity user choices derive from visible events;
  raw event details are admin-only. Project archiving preserves data/permissions
  and excludes the project from active catalog selectors. CAD mutations stay in
  the existing FreeCAD workflows.
- Validation: 98 backend tests, 228 addon tests, 3 Node model tests, 26 existing
  browser checks and 23 management browser checks passed. Migration preservation,
  role/visibility/session boundaries and real browser mutations use disposable
  fixtures. Desktop/mobile screens inspected; tables scroll at readable widths.
  Focused lint, JS syntax and wheel packaging passed.
- Usage/test checklist: docs/web-management.md. Evidence:
  docs/validation/web-management-browser-2026-11-02.json. Phase 5 remains incomplete;
  the user prioritized the functional GUI before independent thorough tests.

## 2026-11-02 — Phase 5 increment 2: atomic assembly check-in (addon 0.6.1)

- Native check-in now publishes exact CAD reference pins in the same transaction
  as file/dataset/manifest, audits, note, fenced lease release and replay result.
  Validate target permissions and exact revision/dataset/file membership at the
  final gate. Shared validation preserves legacy manifest cycle checks.
- Durable client journals retain normalized pins; recovery uses the original
  snapshot and manifest, verifies the server manifest, and reconciles exact pins
  to the local ledger. Prior 0.6.0 empty-manifest journals/fingerprints remain
  compatible. BOM synchronization remains a separate explicit action.
- Nonempty manifests use an explicit new checkin-native-with-references route,
  preventing older servers from silently dropping unknown manifest form fields.
  No migration or legacy check-in fallback.
- Validation: 89 backend and 228 addon tests passed, strict lint for modified
  implementation/tests, addon layout check and addon/backend builds passed.
  Isolated live FreeCAD/HTTP harness passed 28 checks, including nested native
  AssemblyLink occurrences, generated saved child links, lost response, exact pin
  recovery, no duplicates and preserved unsaved edits. User session/data preserved.
  Evidence: docs/validation/phase5-atomic-assembly-checkin-2026-11-02.json.
- Both installed addon profiles updated with backups; runtime command reloaded.
  Phase 5 remains incomplete: legacy-write fencing, revision-creation idempotency
  and recovery/orphan diagnostics remain. See ADR-008 and the Phase 5 plan.

## 2026-11-02 — Phase 5 increment 1: reliable part check-in (addon 0.6.0)

- Added fenced atomic native part check-in and actor-scoped operation status API.
  One metadata transaction publishes File/Dataset/empty manifest, optional note,
  audits, checkout release and immutable replay result. Migration 7 is additive;
  consistent private backup taken before applying it to the local database.
- Recheck lease owner, exact ID/version, expiry, lifecycle and permissions after
  staging, inside the final serialized transaction. Retries return the recorded
  result and do not release a later checkout. Eight-hour/note rules unchanged.
- Addon keeps a credential-free durable snapshot journal. Recover pending/committed
  results before saving current edits; preserve and report edits not included.
  Superseded uncommitted leases require an explicit restart; old snapshots are
  archived. Assemblies/external-reference parts remain on the legacy workflow.
- Isolated live FreeCAD/HTTP validation passed 22 checks: response loss, duplicate-
  free recovery, retained edits, interrupted transfer, renewal rejection, explicit
  restart and worker-thread HTTP. User engineering data/session preserved.
- Backend tests include independent process races, rollback, changed intent/bytes,
  stale/expired/reacquired checkout tokens, permissions, limits and migration
  preservation. Addon tests cover journal/ledger failures and unsupported servers.
- Validation: 77 backend, 223 addon and 3 web model tests passed; 38 targeted
  addon tests also passed after the final private-snapshot/fsync adjustment.
  Addon layout validation and backend/addon package builds passed.
- Both local addon profiles updated with backups; Check In command/client reloaded.
  Design and scope: ADR-008 and docs/phase5-reliable-checkin.md. Live evidence:
  docs/validation/phase5-atomic-part-checkin-2026-11-02.json.
- Limits: blob promotion can leave unreferenced blobs after failure; no orphan
  deletion/reconciliation added. Assembly atomicity, legacy-write fencing and
  revision-creation retry/idempotency remain Phase 5 follow-ups.

## 2026-11-02 — Read-only web GUI (first increment)

- Brought basic Phase 8 web browsing forward with user approval; Phase 5 remains
  the next backend reliability priority. Updated the active roadmap accordingly.
- New same-origin `/app/` client: login/logout, authorized projects/items, search
  and paging, exact revision history, direct/multilevel BOMs, datasets/downloads
  and where-used. Uses the existing bearer API and no frontend runtime/build deps.
- Added optional authorized project_id item filter. Hidden-project membership is
  not disclosed, including items shared into another accessible project. Existing
  unfiltered API behavior remains unchanged. No schema or CAD-client changes.
- Tokens stay in page memory; logout/expiry clears protected UI. Refresh requires
  sign-in. No engineering-data edits, automatic revision adoption or BOM writes.
- 57 backend tests, 3 Node model tests and 26 isolated real Chrome checks passed.
  Desktop/mobile screenshots inspected; authenticated file bytes, XSS text, CSP,
  private-item access, historical pins and session expiry verified. Wheel includes
  all six assets. Targeted new/changed-file checks pass; broad lint has existing
  unrelated findings. Evidence: docs/validation/web-gui-browser-2026-11-02.json.
- Local backend restarted with its existing database/storage and loopback binding;
  `/health` and `/app/` return 200. No production engineering records modified.
- Limits: no web editing, flattened view, CAD rendering or full configuration
  downloads. Individual large downloads use browser Blobs. Browser deployment is
  local only; production security/backup and Phase 5 transaction work remain.
- Design/usage/QA: docs/web-gui.md; README links the local GUI.

## 2026-11-02 — General component replacement (addon 0.5.8)

- Added Replace Component menu/toolbar command with part/assembly-number or name
  search, explicit item/revision/snapshot selection and whole-object mapping.
  Uses the revision replacement engine; the newer-revision shortcut remains
  restricted to the same item. Mapping can change part names/feature types.
- Preserve selected occurrence UUIDs/placements and unselected targets; labels
  reflect the new item. Block direct self-item insertion and unselected internal
  link dependencies that would otherwise silently follow the replaced object.
  Existing checkout/lifecycle, review, joint validity and rollback checks remain.
- 212 addon tests passed; 34 isolated live workflow checks passed, including
  renamed-object cross-item replacement, search/mapping cancellation, grounding,
  unchanged source files and BOM, plus exact pins after separate explicit upload.
  Native different-item assembly replacement and constraint rollback probes passed.
- Both addon profiles updated with backups. Command registered in running
  FreeCAD; main toolbar/menu registration included for future startup.
  Actual A000001 invocation correctly rejected its missing checkout and preserved
  its references, clean state and original selection. No checkout was acquired.
- Evidence: docs/validation/freecad-general-component-replacement-2026-11-02.json
  and docs/validation/freecad-general-native-replacement-2026-11-02.json.
- Limits: native AssemblyLinks still require native Assembly targets. No joint
  remapping or automatic save/upload/BOM synchronization. Inspect changed geometry.

## 2026-11-02 — Explicit component revision replacement (addon 0.5.7)

- Added Replace with New Revision menu/toolbar command. Select direct component
  occurrences, a newer revision and an exact uploaded native snapshot, then review.
  Require clean Working parent, managed working copy and owned checkout.
- Replace link targets in place in one undoable transaction with tree labels.
  Preserve occurrence UUIDs, placements, unselected targets and valid joint links.
  Reject missing/type-incompatible targets and unsafe joint mappings; rollback
  detected failures. Does not save/upload or synchronize BOM automatically.
- 201 addon tests passed; lint, manifest and distribution build passed.
  Twenty-six live isolated workflow checks cover cancel, one-of-two
  replacement, grounding, later explicit upload pin verification and rollback.
  Native subassembly replacement and generated-child constraint rejection tested
  in disposable documents. Actual registered command checklist/cancel tested on
  A000001 without replacing its components.
- Both installed profiles updated with backups. Runtime command/menu/toolbar
  registered; normal future startup adds it to the main ForgePDM toolbar.
- Limits: same internal target object names/types required. Changed face semantics
  cannot be inferred from names; inspect geometry/joints before saving. Native
  generated-child joint mappings may need manual work. Phase 5 atomicity unchanged.
- Design and usage: docs/component-revision-replacement.md and addon README.
  Evidence: docs/validation/freecad-component-replacement-2026-11-02.json and
  docs/validation/freecad-native-replacement-2026-11-02.json.

## 2026-11-02 — Live revision isolation (addon 0.5.6)

- Fixed New Revision mutating the live source document: new revisions now open
  distinct verified working-copy documents, leaving incoming assembly links,
  source metadata, geometry and paths unchanged. Clean/latest Released source
  guards prevent discarding unsaved edits or revising from stale geometry.
- Show BOM reports newer revisions separately while displaying the pinned
  revision; no automatic replacement, BOM update or background polling.
- 184 addon tests passed; targeted lint and manifest/build checks passed.
  Seventeen isolated live FreeCAD/HTTP checks passed, including editing B while
  the existing parent still targets A with unchanged labels/geometry/source hash.
- Actual registered Show BOM dialog verified the pinned Rev A and its newer
  revision B notice; the dialog was inspected and closed without synchronization.
- Repaired A000001's two P000006 links using the recorded uploaded revision A
  pins and original occurrence registry. Local assembly saved cleanly with
  P000006-A|1 and |2; revision B file and stored BOM preserved. A000002's
  already-dirty open document was not saved or closed. Backups kept outside Mod.
- Both installed profiles updated; runtime command classes/client refreshed.
  ADR-007 records the decision. Evidence in docs/validation/freecad-live-revision-
  isolation-2026-11-02.json and freecad-revision-pin-repair-2026-11-02.json.
- Limit: creation/upload still span separate operations (Phase 5); update
  notices are checked on Show BOM, and component adoption is not automated.

## 2026-11-02 — Direct native subassembly BOMs (addon 0.5.5)

- BOM synchronization now captures direct parts and native AssemblyLink
  subassemblies, excluding their generated child links/groups from quantities.
  Repeated occurrences group by exact revision. Child assemblies retain their
  independent BOMs; no recursive CAD flattening or automatic child writes.
- Preserved uploaded snapshot/pin verification, selection/review, checkout and
  optimistic concurrency checks. No backend/schema changes.
- 178 addon tests passed; targeted lint, manifest check and build passed.
- Both installed addon profiles updated with backups; CAD adapter reloaded.
  Live A000002-A produced A000001-A x 1 only, passing real HTTP snapshot/pin
  preparation. All open file hashes and the stored empty BOM were preserved.
  User can complete synchronization through the normal selection/review UI.
- Evidence: docs/validation/freecad-native-subassembly-bom-2026-11-02.json;
  supported boundaries documented in docs/freecad-builtin-assembly.md.

## 2026-11-02 — Native AssemblyLink Python binding (addon 0.5.4)

- Reproduced the setLink binding failure on Assembly::AssemblyLink in a
  disposable live FreeCAD copy. Native references now use LinkedObject property
  assignment; rebasing clears/reassigns the property to invalidate cached paths.
  Reconstruction also uses property assignment for this native type.
- Live installed-code Save As probe preserved all eight exact reference paths
  and all 29 objects. 170 addon tests, targeted lint, package check/build passed.
- Both addon profiles updated with backups; running CAD module reloaded.
- Repaired the failed working copy in place and retried the registered Upload
  command successfully. A000002-A saved cleanly with all eight references
  validated and all generated child labels matching the source subassembly.

## 2026-11-02 — Native subassembly labels (addon 0.5.3)

- Generated AssemblyLink children now project their pinned source occurrence
  labels; only the inserted assembly receives a parent occurrence allocation.
  Source registries, link targets and previous allocation history are preserved.
- Live FreeCAD verification: all seven generated part labels matched their
  exact source occurrences (P000004-B, P000005-A, P000006-A), and the inserted
  assembly displayed A000001-A|1. Existing downloaded configuration was repaired
  in memory; its saved file hash remained unchanged. Normal refresh correctly
  required a working copy for persistent edits.
- 169 addon tests passed; targeted lint, package validation and build passed.
  Both installed profiles updated with backups. Native insertion observer now
  recognizes AssemblyLink. Native subassembly BOM support remains separate.

## 2026-11-02 — Native subassembly upload fix (addon 0.5.2)

- FreeCAD native insertion creates `Assembly::AssemblyLink`, which the exact
  `App::Link` checks previously skipped/rejected. Capture, rebasing, FCStd
  inspection and reconstruction now accept this explicit native link type.
  Subelement/array serialization checks remain enforced.
- Installed in both local addon profiles and reloaded in running FreeCAD.
  The actual registered Upload command succeeded for the open assembly,
  recording its subassembly link and seven generated child references.
  The document remained clean after upload. No credentials recorded.
- Validation: 167 addon tests passed; targeted lint, manifest validation and
  0.5.2 distribution build passed. Added capture, rewrite and rejection tests.
- Limitation: native AssemblyLink BOM synchronization/tree label projection
  remains outside the direct App::Link adapter. A live download roundtrip for
  this new native link type has not yet been validated. Follow up on generated
  child ownership before extending BOM counting; do not flatten subassemblies.


Updated after addon 0.5.1 was pushed to `master` in commit `2ac9c3e`.
This is a handoff for future sessions; verify the current checkout and runtime
before acting. Git history and the linked reports provide the detailed record.

## Current implementation

- Backend: FastAPI, SQLite, separate SHA-256 file storage, authentication,
  project permissions, Items/revisions/datasets, checkout leases, lifecycle,
  revision-pinned BOMs and immutable CAD dependency manifests.
- Web GUI: browsing and controlled user/project/account management at `/app/`,
  served by the backend; see docs/web-gui.md and docs/web-management.md.
- FreeCAD addon: **0.6.5**, modern `freecad.forgepdm` namespace; communicates
  through HTTP without importing backend business logic.
- Development-direction Phases 1–4 are implemented for the documented supported
  structures. Phase 5 implements atomic part/assembly check-in, pinned manifests,
  fenced leases and durable replay; legacy-write fencing and revision retries
  remain pending. The original MVP roadmap has different phase numbering: use the active
  development-direction table in [the roadmap](docs/roadmap.md).
- Live validation has used Linux FreeCAD **1.1.4**, Python **3.11.14**,
  Qt **6.8.3**. Other runtime/platform combinations remain unverified.

## Recent behavior and fixes

- Passwords accept at least four characters, including numeric passwords.
  Local CLI commands support password resets and role changes; see the README.
- Check-in does not prompt for a change note. An omitted note preserves the
  existing revision note. Creating a new revision still requires a note.
- Asynchronous commands refresh FreeCAD command activation when they finish,
  preventing the toolbar from remaining gray until another command runs.
- Show BOM displays the stored engineering BOM. CAD synchronization is a
  separate reviewed action: it verifies saved/uploaded snapshots and exact
  component revisions before proposing replacement lines.
- The bounded native Assembly adapter supports direct whole-object App::Link
  components and excludes standard joints from quantities. Unsupported layouts
  require an adapter; this is not general support for every assembly workbench.
- Tree labels use `ITEM-REVISION|OCCURRENCE`, for example `P000005-A|2`.
  Numbers are scoped to the immediate parent and exact component revision;
  persistent UUIDs and allocation history preserve surviving occurrences.
  Deleted indices are not reused. Display labels never determine PDM identity.
- Addon 0.4.3 changed reconstruction to GUI document save so the GUI Modified
  flag clears correctly. Version 0.5.1 additionally recomputes after tree-label
  projection: legacy FeaturePython metadata can remain Touched after a save.
  Both clean-state guards remain enforced; unresolved edits are not discarded.

## Latest validation

- **162 addon tests passed** after the 0.5.1 fix. The preceding 0.5.0 validation
  recorded **54 backend tests passed**; the latest fix did not change backend code.
- Manifest/package build and targeted lint checks passed for 0.5.1.
- The exact assembly snapshot that failed on retrieved component `P000005-A`
  was retried through the actual registered Download command in live FreeCAD.
  The root and three component documents opened cleanly, all four occurrence
  links used their exact pinned revisions, and previous open documents and file
  bytes were preserved. Dialog choices/notifications were automated; real CAD,
  worker and HTTP paths executed.
- Both local FreeCAD addon profiles were backed up and updated to 0.5.1.
  The running CAD module was reloaded. Do not assume a future runtime still has
  the same version, active documents, authenticated session or running services.

Evidence:

- [Legacy snapshot download](docs/validation/freecad-legacy-label-download-2026-11-01.json)
- [Tree labels and occurrence identity](docs/freecad-tree-labels.md)
- [Phase 4 BOM synchronization](docs/freecad-addon-phase4.md)
- [Native Assembly profile](docs/freecad-builtin-assembly.md)
- [Detailed runtime validation](clients/freecad/Documentation/validation.md)
- [Addon changelog](clients/freecad/CHANGELOG.md)

## Next session

1. Read root and applicable nested `AGENTS.md`, inspect Git status and recent
   commits, and confirm the user's requested scope. The next feature priority is
   the personal component catalog: start with docs/component-catalog-plan.md and
   its domain/schema design increment. Phase 5 is authorized and
   started; the first two bounded increments are complete. The user subsequently
   prioritized functional web management and independent thorough testing; use
   docs/web-management.md for the implemented GUI and suggested test sequence.
2. For CAD issues, confirm installed addon/runtime versions and reproduce with
   the actual document structure. Distinguish mocked tests from live validation.
   Preserve existing edits, immutable snapshots and exact revision pins.
3. After the catalog priority, or when explicitly requested, continue Phase 5 from ADR-008 and
   docs/phase5-reliable-checkin.md when requested. Next,
   fence remaining legacy writes and address revision-creation retries. Propose the
   next design increment before major architectural changes.
4. Track later operational work separately: crash-orphan reconciliation,
   backup/restore, production security, clean-start/platform acceptance and
   distribution gates. Refer to the roadmap rather than treating this prototype
   as production-ready.

## Verification commands

Run from the repository root:

```sh
uv run --project clients/freecad --extra dev pytest clients/freecad/tests -q
uv run --group dev pytest tests -q
uv run --project clients/freecad --extra dev python clients/freecad/tools/addon.py check
uv run --project clients/freecad --extra dev python clients/freecad/tools/addon.py build
```

Use the runtime harnesses documented in the validation guide when real FreeCAD
verification is required. Never store passwords or bearer tokens in this file.
