# Changelog

## 0.3.0 — managed workspace and pinned CAD references

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
