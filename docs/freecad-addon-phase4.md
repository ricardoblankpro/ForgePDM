# Phase 4 — BOM extraction and assembly synchronization

Status: implemented for the bounded whole-object App::Link profile in addon
0.4.0. See [ADR-005](decisions/ADR-005-reviewed-bom-synchronization.md).

## User workflow

Save/upload components and then their assembly. On a Working assembly with your
active checkout, open **Show ForgePDM BOM → Synchronize from CAD…**. Select the
engineering occurrences to include; nothing is selected implicitly. Review
quantity changes, complete current/proposed lines, exact revision IDs and source
occurrence names. Check the explicit replacement consent before submitting.
Cancel preserves current/manual engineering lines. An approved empty proposal
removes all lines, with an explicit empty-BOM message in the review.

Every selected whole-object link contributes one unit. Repeated internal links
resolve to the same pinned external component and add units. Plain groups/parts
organize occurrences within the source document. Linked external assemblies remain
single direct components; their children are not flattened. Revision IDs, rather
than labels or filenames, determine grouping. Historical A remains A after B exists.
Deterministic object/property ordering assigns proposed positions from one.
Manual positions and split lines are displayed but replaced on approval.

Arrays, subelements, unresolved links, local geometry/group link targets,
external link-to-link targets, custom proxies and unsupported assembly object
types are rejected. Local geometry is explicitly excluded. Hidden/template links
are candidates and can be excluded by selection. This does not certify Assembly,
Assembly3, Assembly4 or other third-party adapters.

## Consistency and API

The GUI thread captures live document identities and detects unsaved changes with
both touched state and `Gui.Document.Modified`; recompute alone clears touched
state. Worker requests verify root/child workspace hashes, exact uploaded dataset/
file/object pins and the root manifest. The GUI checks document identity, revision,
saved path and occurrences again after review. Worker verification repeats before
the write. Workspaces, cache blobs and CAD geometry are never edited by extraction.

Additive endpoints:

- `GET /api/v1/revisions/{id}/bom/snapshot`: editable direct lines, opaque `token`
  and active owned `checkout_id` from one database transaction.
- `PUT /api/v1/revisions/{id}/bom/synchronize`: `lines`, `expected_token` and
  `expected_checkout_id`. Checks both preconditions in the same write transaction
  as replacement. Competing proposals have one winner; stale proposals get 409.

Existing replacement/read endpoints and schema version 6 remain compatible.
Existing authorization, active checkout, Working state, positive quantities,
component access, obsolete-component and cycle policies still apply. The result
is read inside the replacement transaction. Unknown write outcomes are reported
by the worker engine and never automatically retried; inspect the server BOM
before preparing another proposal. This is not general mutation idempotency or
atomic upload/check-in, which remain Phase 5.

CAD dependencies and engineering components are distinct. Retrieval now records
`bom_revision_check: differs` when revision sets differ, while reconstructing only
the exact CAD manifest. It no longer rejects valid CAD solely because engineering
selection/manual BOM lines differ. Hash, permission and CAD reference checks
remain enforced. Matching revision sets do not certify matching quantities.

Occurrence provenance is retained in the review proposal, not persisted as an
authoritative server CAD-to-BOM mapping. The server validates the engineering BOM,
not a client's geometry/extraction claim. Uploading changed CAD does not silently
resynchronize it; synchronization remains an explicit operation.

## Validation

Automated suites cover exact-revision quantities/provenance, explicit selection,
quantity differences including manual split lines, rejected structures, source/
child snapshot changes, permissions, HTTP validation, stale proposals, lease
replacement and concurrent competing writes, plus prior backend/addon regressions.
Packaging tests validate deterministic builds, isolated imports, command IDs,
resource translations and the official vendored manifest schema.

Final automated results: **34 backend tests passed**, **115 addon tests passed**.
Addon lint and targeted backend lint/format checks pass, as does `git diff --check`.
The standalone `clients/freecad/dist/ForgePDM-0.4.0.zip` passes offline manifest/
layout validation. No repository-wide clean lint baseline is claimed.

Live GUI validation used Linux FreeCAD **1.1.4**, Python **3.11.14**, Qt **6.8.3**,
the running local MCP bridge and a separate temporary HTTP backend with disposable
credentials, metadata, blobs and CAD documents. Actual dialogs ran with automated
choices. Tests covered the public Show BOM command, internal repeated occurrences,
nested assemblies, placement preservation, historical revision A after B exists,
explicit replacement consent, canceled review, edits during review, array rejection,
HTTP stale-review rejection and worker/GUI thread separation. See
[the live report](validation/freecad-phase4-2026-11-01.json) and the reproducible
`clients/freecad/tests/freecad_phase4_smoke.py` harness. User documents and data
were not used as fixtures. Live testing reloaded source modules; clean-start UX,
other FreeCAD versions/operating systems and third-party adapters remain unverified.

Restart the updated backend before using these additive endpoints; no new database
migration is required. Build/install addon 0.4.0 and restart FreeCAD. No user-profile
installation, production deployment, commit, push or public release is performed
by this phase.
