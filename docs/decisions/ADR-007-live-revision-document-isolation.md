# ADR-007 — Isolate live CAD documents when creating revisions

Status: accepted, 2026-11-02, implementing the user's revision-pinning policy.

## Problem

The previous New Revision command modified the source document's revision metadata
and called Save As on that same live FreeCAD document. Other open documents still
held links to its objects, so creating part B silently changed assembly geometry
and projected labels from A to B, even though the stored engineering BOM and
uploaded dependency manifests remained pinned to A. Preserving the old file alone
was insufficient to preserve the live assembly configuration.

## Decision

Create a verified copy of the clean saved source, rebase external reference paths
in that copy, then open it as a distinct FreeCAD document. Apply the new revision
metadata only to the new document. Keep the original document, object identity,
file path, geometry, occurrence registry and incoming links unchanged. Require the
selected source to be the current Released revision and reject unsaved source
changes rather than discarding them. Copying and hashing execute in the existing
worker; FreeCAD object operations stay on the GUI thread.

Show BOM compares its pinned component revisions with each item's current
revision through read-only API requests. A newer revision is reported separately;
it does not change the BOM, CAD link target or occurrence label. Checks happen on
explicit BOM display, not at addon startup. Adopting a newer component remains an
explicit engineering change under checkout and normal revision/lifecycle rules;
this change does not add an automatic adoption command.

This is analogous to precise/as-stored configuration in commercial PDM systems.
It intentionally does not introduce rule-based latest-revision loading. CAD
reference manifests and engineering BOMs remain distinct authoritative records.
No backend schema/API contract changes are needed.

## Validation and limits

Regression coverage includes source/copy path integrity, unchanged incoming live
links, clean/historical source guards, independent new revision metadata and
read-only newer-revision notices. Live FreeCAD validation creates A, a parent with
two occurrences, releases A, creates B through the actual command workflow and
edits B; the existing parent retains A's geometry, labels and UUIDs. Historical
retrieval also preserves A. Existing source files are hashed for preservation.

Server revision creation and the subsequent upload remain separate operations.
Failure recovery, fencing and idempotency remain Phase 5 work; the workflow does
not claim an atomic transaction across GUI state, files and server metadata.
The source must be saved; this workflow does not revise unsaved edits. Other
FreeCAD versions/platforms remain outside the current live validation scope.
