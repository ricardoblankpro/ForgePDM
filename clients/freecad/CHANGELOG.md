# Changelog

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
