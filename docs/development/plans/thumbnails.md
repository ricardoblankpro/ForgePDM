# Future implementation — shared CAD thumbnails

Status: requested for future work; **not implemented**. Recorded 2026-11-12.

## Goal

Show the same thumbnail for an exact uploaded CAD snapshot in the FreeCAD browser
and web GUI. Start with a preview of the selected item; thumbnails in every result
row can follow with caching/lazy loading. Keep names optional and item numbers
prominent. A missing thumbnail shows a placeholder and does not block opening.

## Proposed first increment

1. Generate a small PNG in FreeCAD as part of preparing new upload/check-in
   snapshots. Investigate whether an existing embedded FCStd preview is sufficient
   before introducing an extra rendering step. The image must describe the saved
   bytes, not newer unsaved geometry. Preserve the user's camera, visibility,
   selection, active document, dirty state and original file bytes.
2. Store/associate the thumbnail with the immutable source dataset/file and its
   content hash, using bounded validated image ingest. Replays/retries must reuse
   the same association or detect changed intent; never attach a newer preview to
   an older snapshot. Define explicitly whether optional thumbnail failure leaves
   the CAD upload successful with a placeholder and a retryable preview operation.
3. Serve through authorized APIs: access follows source revision/dataset
   permission. Apply response size/type validation and cache by exact source
   identity. Do not persist credentials in thumbnail URLs, preferences or logs.
4. Add the selected-snapshot preview to both FreeCAD and web clients. Changing
   revision/snapshot invalidates stale image responses. Include placeholders,
   loading/error states and accessibility text; do not slow down search/opening.
5. Test hash/snapshot association, duplicate/lost-response recovery, authorization,
   image limits, stale UI responses and real native camera/document preservation.

## Follow-ups and boundaries

- Explicit “Generate missing thumbnails” for existing files, using disposable
  reconstruction where required. Never silently open/save/modify production CAD.
- Per-row thumbnails with lazy loading and bounded disk/memory caches.
- Backend/headless FreeCAD rendering is a separate, more complex deployment
  increment; no rendering service is assumed for the first version.
- Define retention alongside immutable CAD storage and offline orphan diagnosis.
  No inventory, material mass, lifecycle or BOM rules change.

Estimated difficulty is moderate for new uploads with FreeCAD generation; batch
backfill/headless rendering and cross-platform acceptance are larger follow-ups.
The exact API/schema and failure policy need a concrete plan before implementation.
