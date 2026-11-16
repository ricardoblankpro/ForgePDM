# ADR-025 — Immutable isometric previews of exact CAD snapshots

Date: 2026-11-16

Status: Accepted. The owner selected standard isometric orientation.

## Context

The native browser and web workspace identify exact CAD uploads but previously
offered no shared image. FreeCAD embeds a preview in FCStd files, but that image
is not a sufficient contract for the agreed fixed orientation. A screenshot of
newer unsaved geometry must never represent an older immutable upload.

## Decision

Generate an optional 384 by 384 PNG immediately after the existing native save in
Upload and Check In. Temporarily disable view animation, use orthographic
isometric orientation, fit the visible saved model, clear selection highlights
and render on white. Restore the full camera/type, animation setting and
selection afterward. Do not change object visibility or save for the preview.
Restore native Coin camera fields directly; text serialization/reparsing can
renormalize perspective rotations and accumulate floating-point drift.
Reject dirty documents and dirty linked components, including recomputed GUI
modified state. Guard root/dependency file hashes before/after capture; cap each
file at 256 MiB and the dependency set at 1000 documents. Use an existing 3D view;
never activate/reconstruct another production document for an automatic preview.

Carry image bytes and the captured source hash to the upload worker. Associate
only when that hash equals the immutable prepared CAD snapshot. Check-in stores
a private, hashed image sidecar and intent in its existing durable operation
journal. Retries reuse the original image, never a new screenshot of current
edits. Lost image responses may retry the identical attachment safely.

The backend adds migration 18, `file_thumbnails`, linking source and image `files`
rows. Each source file gets one immutable `isometric-v1` association, including
the raw-input hash and declared source hash. Same intent is idempotent; different
intent conflicts. Accept at most 1 MiB, 512 by 512, single-frame PNG; validate
and re-encode through Pillow, strip metadata and bound compressed text decoding.
Image bytes use existing immutable SHA-256 storage, so recovery diagnostics and
backups include them. Snapshot backup verification accepts known migration
prefixes, preserving schema-17 backup retrieval without migrating the archive.

Read access follows the exact source revision. New attachment requires current
editor access and either the source uploader or an administrator. It needs no
checkout and may finish after check-in/release because it adds a derivative,
never modifies engineering bytes, lifecycle or BOM. This limited policy is
explicitly separate from ordinary CAD/file writes. Disabled actors are rejected.
An image file has no independent public dataset/download identity.

Expose authenticated POST/GET `/api/v1/files/{source_file_id}/thumbnail`.
POST accepts bounded base64 PNG JSON and source hash. GET verifies stored bytes,
returns source/hash headers, `image/png`, `nosniff` and private/no-store policy.
Clients validate source identity, image hash, type, dimensions and byte limits.
No credentials enter image URLs. The web uses short-lived blob URLs and revokes
them; native Qt decodes only on its GUI thread. Selection epochs, cancellation
and session checks prevent stale responses from replacing current content.

Show one selected-snapshot preview in the native browser and web Overview/Files.
Missing/failed previews show placeholders and never block CAD opening or undo a
successful CAD upload/check-in. A pending check-in preview can retry with Check
In while that operation remains current. Normal Upload warns on optional failure;
there is no independent batch-repair UI in this increment.

## Boundaries

No automatic backfill, per-row images, persistent image cache, headless rendering
service, drawing-sheet rendering or regeneration/replacement of existing images.
Existing CAD snapshots remain untouched. Backups include the derivatives but
retain their existing same-drive/retention limits. Software licenses and public
contact remain unchanged; Pillow is a separately installed backend dependency,
not copied into or required by the addon.

## References

- [Current user workflow](../user/freecad.md#snapshot-previews)
- [Pillow decoding and image limits](https://pillow.readthedocs.io/en/stable/reference/Image.html)
- [Pillow PNG behavior](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#png)
- [FreeCAD screenshot command](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/Std_ViewScreenShot.md)
