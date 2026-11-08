# Changelog

## 0.10.0 — 2026-11-07

- Automatically retrieve verified supplier reference mass when registering supported
  S fasteners; reuse saved revision mass during association. Missing data or supplier
  outages do not block registration. Backend migration 16 required.
- Add exact-specification supplier CSV import and a simple S mass/provenance web view.
  Released revisions stay unchanged; assembly mass totals remain future work.

## 0.9.1 — 2026-11-07

- Upgrade matching legacy description metadata during upload/check-in preparation,
  applying the saved physical material and generating native mass evidence.
- Rebuild missing mass metadata in matching v2 working copies without replacing
  conflicting local material edits.

## 0.9.0 — 2026-11-07

- Register raw materials in one native dialog with description and physical material;
  link existing M entries with curator/checkout protection.
- Apply native density snapshots on P parts, calculate final-solid mass and refresh
  it after owned-document geometry recompute and before publication.
- Preserve source-pinned mass through atomic upload/check-in and portable retrieval.
  Existing description-only entries and assembly descriptions remain supported.
- Requires backend migration 15. Managed density cache cards do not overwrite
  original FreeCAD material cards; FEM/thermal models are not synchronized.

## 0.8.1 — 2026-11-07

- Replace manufacturing-input prompts with M-only material selection for P parts
  and free-text descriptions for A assemblies.
- Add one Description tree column beside existing PDM status.
- Persist revision-bound descriptions through atomic native publication and
  configuration retrieval. Preserve historical material/BOM records.
- Requires backend migration 14 for the simple description workflow.

## 0.8.0 — 2026-11-07

- Assign catalog M/S manufacturing inputs to Working P/A revisions.
- Calculate selected-solid mass from pinned material density, preserving multiple materials.
- Embed revision-bound evidence for atomic upload/check-in; detect conflicting web edits.
- Requires backend migration 13 for material workflows; existing commands remain supported.

## 0.7.4 — 2026-11-05

- Register all S items in the shared Standard Parts Library without a project
  prompt, including Fasteners registration and native purchased-part uploads.
- Require shared-library backend capability and maintainer rights before
  registration. Existing library parts remain reusable by readers.
- Requires backend migration 12; existing item/revision/BOM identities are retained.

## 0.7.3 — 2026-11-05

- Replace fastener material/grade/finish text prompts with one controlled selection
  form, dependent mechanical/finish options and an extended-options view.
- Generate uppercase catalog name/description in TYPE MATERIAL FAMILY NORM
  DIMENSION GRADE FINISH order. Show the complete name before registration;
  require explicit classification for unrecognized standards.
- Preserve legacy catalog text and specification values. Generic purchased-item
  registration remains available when there is no Fasteners geometry schema.

## 0.7.2 — 2026-11-05

- Add Change Standard Part Association for selected direct Fasteners objects.
  Choose an existing matching S specification or register another grade/material/
  finish; retain occurrence UUIDs, geometry, placements and unselected associations.
- Require an owned Working assembly checkout and recheck it after review.
  Changes are undoable and remain local until explicit Upload and BOM review.

## 0.7.1 — 2026-11-05

- Accept qualified local Fasteners attachment paths produced by native Assembly
  selection, such as Body002.Hole.Edge5. Validate the full path against a non-null
  shape; preserve exact external-link pins and the existing external adapter limits.

## 0.7.0 — 2026-11-05

- Add S-numbered standard/purchased items and metadata-only registration.
- Resolve Fasteners catalog associations during Upload and Check In, with grouped
  confirmation, missing-item registration, exact revision pins and edit detection.
- Preserve embedded occurrence evidence and managed external attachments; include
  associated fasteners in explicitly reviewed mixed BOM proposals.
- Require backend migrations 10–11 and Fasteners integration capability.
- See docs/standard-parts.md for validated versions and unsupported cases.

## 0.6.6 — 2026-11-03

- Add Publish Drawing PDFs: review selected TechDraw pages, render an isolated
  verified native snapshot and publish one immutable PDF per page. Require an
  owned Working checkout; preserve the original documents and checkout.
- Retain frozen PDFs and a credential-free operation journal for safe retry after
  response loss. Requires backend drawing-publication support and migration 9.
- Add web Drawings preview/download, publication history, exact source details
  and newer-native-snapshot warnings. Publication is separate from native check-in.

## 0.6.5 — 2026-11-03

- Support TechDraw SVG templates proven embedded and self-contained in native
  FCStd snapshots. Preserve page/title/dimension data and restore without the
  uploader's original template file. Keep other external-asset guards intact.
- Settle native TechDraw background projection before saving managed/retrieved
  snapshots; exclude drawing documentation from assembly BOM quantities.
- Distinguish local CAD validation failures from uncertain server writes, while
  retaining clear warnings about earlier successful operations.

## 0.6.4 — 2026-11-03

- Add Refresh PDM Status and an ephemeral native-tree column for checkout owners,
  released revisions, newer revisions and per-occurrence newer snapshots. Colored
  badges/text/tooltips preserve native icons, CAD labels and document clean state.
- After explicit activation, refresh in the background every 60 seconds and after
  PDM commands. Handle stale/offline results and clear private data on logout or
  account changes. Requires the additive authorized backend batch-status endpoint.

## 0.6.3 — 2026-11-03

- Add Update Selected Components from Server for reviewed same-revision snapshot
  replacement in owned clean uploaded Working assemblies. Preserve occurrence
  identities, labels, placements and unselected targets; check joints and rollback
  failures. Recheck original pins, parent bytes and lease after review. Leave the
  assembly modified for inspection and separate explicit check-in.

## 0.6.2 — 2026-11-03

- Add Update from Server to compare the active managed revision with its latest
  native upload and open a reviewed verified copy, preserving original documents
  and incoming assembly links. Block dirty/unuploaded local changes and pending
  check-in recovery; report newer revisions without automatically adopting them.

## 0.6.1 — 2026-11-02

- Extend atomic check-in to assemblies and external-reference parts. Publish
  exact occurrence/revision/dataset/file pins together with native bytes, audits
  and fenced checkout release. Preserve these pins through retries and recovery.
- Use an explicit manifest endpoint so older servers cannot ignore references.
  Update/restart the backend with the addon; no legacy check-in fallback.
- Validate real nested native AssemblyLink occurrences, generated child links,
  lost responses and retained unsaved edits in isolated FreeCAD/HTTP tests.

## 0.6.0 — 2026-11-02

- Eligible part check-in now uses one fenced, replayable backend operation.
  Persist a credential-free journal and immutable snapshot to recover timeouts,
  interrupted transfers and local ledger failures without duplicate datasets.
- Recheck exact checkout ID/version after upload; preserve original pending
  snapshots and require explicit restart when their lease is superseded.
- Assemblies and parts with external references retain the existing multi-request
  check-in path pending the next Phase 5 increment. Update the backend together
  with this addon; no automatic downgrade to legacy part check-in is performed.


## 0.5.8 — 2026-11-02

- Add Replace Component with item-number/name search, explicit revision and
  snapshot selection, and whole-object mapping across different items/names.
- Share occurrence selection, checkout/lifecycle guards, review, placement/joint
  preservation and rollback with Replace with New Revision. Keep that shortcut
  restricted to newer revisions of the same item.
- Update item labels without changing occurrence UUIDs. Save/upload and reviewed
  engineering BOM synchronization remain separate actions.


## 0.5.7 — 2026-11-02

- Add Replace with New Revision for reviewed direct component occurrences.
  Choose the newer revision and uploaded native snapshot explicitly.
- Retain link objects, placements, occurrence UUIDs and valid joint references;
  roll back local replacement failures. Require a clean Working parent and owned
  checkout. Save/upload and BOM synchronization remain separate actions.


## 0.5.6 — 2026-11-02

- Create next revisions in distinct FreeCAD documents from verified saved copies.
  Existing live assembly links keep the original revision and geometry.
- Require a clean source at the latest Released revision; preserve historical
  documents and reject source changes during preparation.
- Show BOM reports newer component revisions without replacing pinned revisions.
  Preserve indentation when displaying nested BOM text.


## 0.5.5 — 2026-11-02

- Synchronize native assembly BOMs from direct parts and AssemblyLink
  subassemblies. Exclude generated subassembly children from parent quantities.
- Preserve exact revision pins, repeated occurrence quantities, snapshot checks
  and explicit selection/review. Subassemblies own their independent BOMs.


## 0.5.4 — 2026-11-02

- Rebase native AssemblyLink references through their LinkedObject property;
  FreeCAD's inherited setLink Python binding fails for this native type.
- Use native property assignment when restoring pinned AssemblyLink targets.


## 0.5.3 — 2026-11-02

- Project native subassembly generated child labels from the exact linked source
  occurrences instead of assigning the subassembly identity to every part.
- Allocate a parent occurrence for the AssemblyLink itself and observe native
  subassembly insertion for deferred label refresh.


## 0.5.2 — 2026-11-02

- Accept whole-object native `Assembly::AssemblyLink` references during upload,
  path rebasing and pinned reconstruction. Keep subelement/array rejection.
- Native subassembly BOM synchronization remains outside the current direct
  App::Link BOM adapter.


## 0.5.1 — legacy component retrieval after tree-label projection

- Recompute loader-created occurrence metadata before saving reconstructed
  documents. A successful GUI save alone does not clear FeaturePython Touched.
- Keep the strict saved-state guard; genuine unresolved touches still prevent
  completion. Preserve legacy blobs and historical occurrence labels/identities.

## 0.5.0 — persistent tree occurrence labels

- Show managed component links as ITEM-REVISION|OCCURRENCE with persistent UUIDs,
  parent/revision-scoped numbering and retained allocation history.
- Preserve surviving indices after deletion and allocate fresh identities/numbers
  for copied links. Keep names, reference pins and BOM quantities independent.
- Add Refresh ForgePDM Tree Labels; project labels during upload and owned
  retrieval, and after insertion under a previously verified owned checkout.

## 0.4.3 — clean state after configuration retrieval

- Save reconstruction metadata/link changes through FreeCAD's GUI document save,
  preventing downloaded components from retaining a false unsaved-change flag.
- Keep genuine edits blocked during BOM synchronization and retain modified
  documents on failed reconstruction. Identify the affected component in errors.

## 0.4.2 — native Assembly BOM support

- Accept a single native Assembly container with direct whole-object App::Link
  components; exclude its standard joint group and Joint/GroundedJoint objects.
- Reject nested local assemblies, stray links and unknown proxies/types with
  object-specific explanations. Keep pinned component verification and review.

## 0.4.1 — check-in and toolbar fixes

- Remove the change-note prompt from check-in. The updated backend accepts
  check-in without a note and preserves an existing revision note when omitted.
- Refresh command activation when asynchronous workflows start and finish so
  toolbar/menu actions recover after success, cancellation and errors.

## 0.4.0 — reviewed engineering BOM synchronization

- Add occurrence selection and BOM replacement review to Show ForgePDM BOM.
- Count supported external links and repeated internal links by exact revision;
  keep linked subassemblies as direct components rather than flattening them.
- Verify uploaded assembly/component snapshots before review and before writing.
- Reject stale BOM snapshots and replaced checkout leases in one server transaction.
- Preserve manual lines until explicit replacement consent; never retry uncertain writes.
- Distinguish CAD dependencies from engineering components during retrieval.
- Requires the additive Phase 4 synchronization API; schema remains version 6.

## 0.3.0 — managed workspace and pinned CAD references

- Give each command its own original SVG icon, matching the Workbench palette.
- Fork source and next-revision files into isolated managed working copies.
- Upload verified snapshots with immutable exact dependency manifests.
- Retrieve nested whole-object App::Link configurations through verified cache,
  relative path rewriting and GUI document/object validation.
- Preserve dirty local files; reject inaccessible, corrupt or mismatched graphs.
- Keep engineering BOM synchronization and atomic check-in for later phases.
- Requires the additive Phase 3 backend manifest API and migration 6.

## 0.2.0 — connectivity and catalog browsing

- Run all HTTP requests and file transfers in a worker, with GUI-thread
  continuations, progress, cooperative cancellation and no automatic retries.
- Remember server URL, username and request timeout without storing passwords
  or bearer tokens; clear expired/revoked sessions and provide recovery messages.
- Select authorized projects by number/name and browse items and historical
  revisions through additive, permission-filtered catalog API endpoints.
- Keep existing command IDs and authoritative PDM editing rules unchanged.

## 0.1.0 — development preview

- Migrate existing commands to the modern `freecad.forgepdm` namespace.
- Add standalone ZIP packaging, offline manifest checks and original SVG icon.
- Preserve command IDs, document metadata and backend API requests.
- Prompt for a writable copy when uploading a read-only document, such as a
  bundled FreeCAD example inside an AppImage; report save failures with the path.
- Explain project IDs versus project numbers, reject malformed IDs before item
  creation, and display readable API validation messages instead of raw errors.
- Actual FreeCAD GUI validation and public distribution approval remain pending.
