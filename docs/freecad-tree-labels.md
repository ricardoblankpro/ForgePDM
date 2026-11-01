# Tree labels and occurrence numbering — addon 0.5.0

## Behavior

Managed component links display `P000001-B|1` (or `A000003-C|1` for an external
subassembly). The suffix identifies an occurrence of the exact target Item/Revision
inside its immediate assembly container. Another target revision or another parent
has its own sequence. Ordinary document folders do not create an engineering scope.
Uncontained links use the document scope. Native Assembly containers and plain
App::Part containers are supported; external subassemblies define their child
occurrences in their own documents. No latest-revision lookup is performed.

Numbers are stable across reordering, save/reopen and upload/retrieval. Deleting
an occurrence leaves gaps; its number is not reused. A copied App::Link carrying
the source's properties receives a fresh UUID and next index. Moving an occurrence
to a different parent or target revision keeps its UUID and allocates in the new
sequence. New revisions of the owning assembly preserve lineage; a new owning
Item reseeds occurrence UUIDs. Labels are never parsed for identity. Object Names,
link targets and manifest pins remain the reference identities. BOM positions and
quantities remain independent; tree numbering does not synchronize the BOM.

## Persisted data

- Link properties: `ForgePDMOccurrenceId`, `ForgePDMOccurrenceNumber`,
  `ForgePDMOccurrenceKey`, and `ForgePDMOriginalLabel`.
- Existing hidden document metadata: versioned `TreeOccurrenceState` JSON with
  per-scope high-water marks and UUID ownership, plus `TreeOriginalLabel`.

These properties appear read-only in the property editor. Allocation is planned
before mutation, conflicting property types/invalid registries are rejected, and
CAD changes use a transaction. The registry retains deletion history. Source files
and local copies carry the data; no backend/API/schema migration is introduced.

The document heading projects `ITEM-REVISION`; original descriptions are retained
on first projection. FreeCAD itself resets the document heading from the filename
on a raw File > Open. Stored link labels/IDs remain intact. ForgePDM retrieval or
Refresh Tree Labels reapplies the document heading without reallocating indices.
Legacy snapshots without occurrence metadata get a local projection; a normal
managed upload persists it. Immutable historical blobs are never rewritten.

## Workflows and permissions

**Refresh ForgePDM Tree Labels** is an additive toolbar/menu command. It checks the
Working revision and current owned checkout through authenticated HTTP, requires
a managed working copy, then projects the labels. Save/upload persists changes.
Checkout and upload also project labels. New item/revision uploads save the label
metadata before hashing and ingest; native Save As/relink operations complete
their controlled transactions before presentation changes. Managed retrieval
projects only its newly owned copies before GUI save, verification, hash and
read-only finalization. Already-open dependencies and cache/server bytes are not
rewritten or dirtied by labeling a parent.

A debounced GUI document observer updates inserted/copied links and parent/target
metadata changes after native editing transactions complete. It is enabled only
for a working document whose owned, unexpired checkout was verified by a prior
ForgePDM command. Session/user/server/document/revision changes and local check-in
or release disable that cached permission. The observer does no network work at
startup, makes no server writes and waits while a ForgePDM job/modal/native edit
is active. The lease cache is local editing guidance; the server rechecks all PDM
rules on mutations. An external lease revocation is discovered on the next server
operation. Raw file-open users can verify editing permission via checkout/refresh.

Unmanaged/foreign links, local geometry links, arrays and subelements retain their
labels and receive no guessed occurrence number. Explicit refresh reports skipped
links. Link/container cycles and ambiguous parent ownership are rejected rather
than choosing a parent arbitrarily. Existing BOM adapter limitations still apply;
labeling an object does not certify it for engineering BOM extraction.

## Validation

The automated suite covers exact-revision/parent grouping, stable deletion history,
copied properties, reparenting, revision changes, owner-item changes, malformed
registries, description retention, idempotence, pending native edits, permissions,
observer deferral/revocation, isolated imports and ten-command packaging.
Final results: **160 addon tests** and **54 backend regression tests** passed.
Addon lint/format, deterministic packaging/manifest checks and `git diff --check`
pass. No repository-wide backend lint baseline is claimed.

Real Linux FreeCAD **1.1.4**, Python **3.11.14**, Qt **6.8.3** validation includes:

- **18 disposable CAD checks**: repeated links, native copy/delete, no reused
  indices, reordering, subassembly scopes, save/reopen, observer insertion after
  transaction completion, explicit target revision changes and revoked permission.
  The standalone observer fixture uses an injected lease; it makes no server writes.
- **12 isolated HTTP/CAD checks** through real upload, check-in, release, next
  revision and historical retrieval workflows. Prior files, historical occurrence
  UUIDs, exact revision A labels after B exists, clean reconstructed state and
  unchanged geometry are checked. Temporary credentials are not in the report.
- **7 current-assembly checks** through the real Refresh Tree Labels and Upload
  commands. The precondition was a clean, already-uploaded owned working copy.
  A native-file backup preceded application. Four links now display P000004-B|1,
  P000005-A|1, P000006-A|1 and P000005-A|2. Internal names, shapes, placements,
  grounding, linked component bytes and engineering BOM lines/quantities matched
  the pre-label state. The actual tree widget rendered all four expected labels.

Reports and harnesses are linked in
[the combined live report](validation/freecad-tree-labels-2026-11-01.json).
Both installed addon profiles were backed up and updated; the running session
registered the additional command and observer. Other OS/FreeCAD versions,
third-party assembly adapters and long-running multiuser lease changes remain
outside this live certification. No repository push or public release is implied.
