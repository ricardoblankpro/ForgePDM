# ADR-008 — Atomic part check-in with fenced leases and replay

Status: accepted implementation direction, 2026-11-02. The user authorized Phase 5
following the proposed reliable single-part check-in increment.

## Problem

The addon currently uploads a dataset, attaches its dependency manifest and checks
in via three independent HTTP transactions. A timeout can leave an unmanifested
file, duplicate datasets on retry, or an unclear checkout result. Ownership alone
cannot distinguish an old operation from a later checkout held by the same user.

## First increment

Add a versioned multipart native check-in operation for **parts with no external
CAD references**. Keep legacy operations compatible; do not claim that assembly
or legacy requests gain these guarantees. Checkout duration remains eight hours;
check-in notes remain optional and blank notes preserve the stored revision note.

The request identifies one operation UUID, the exact checkout UUID/version, and
the intended SHA-256/byte size. Hash and stage the uploaded bytes outside a DB
write transaction. Promote and verify the content-addressed blob, then use one
`BEGIN IMMEDIATE` transaction to recheck permissions, Working state, lease owner,
lease ID/version and expiration, and commit File, Dataset, empty manifest, audit,
revision note, checkout release and the immutable operation result together.

An additive operation table is keyed by actor and operation UUID. Fingerprints
include revision, lease, content hash/size, normalized filename/media type and
note. Reusing a key with different intent is a conflict. Replaying the same
completed operation returns its recorded result, even after the lease is released
or another checkout is acquired. It must not release or modify the new checkout.
Current read permission is still required. A read-only status endpoint resolves
lost responses without uploading again; other actors cannot query the operation.

The acceptance point is the lease check inside the serialized final transaction,
after upload/staging. Renewal increments the existing lease version, so an
in-flight request carrying an older version is rejected and must be reviewed
again. Same-user release/reacquisition also changes the checkout ID. The blob is
verified before metadata can reference it. Rollback never deletes a shared blob.

## Client recovery

Persist a private workspace journal with operation ID, actor, revision, original
checkout token, immutable snapshot hash/size/path and final result. No credentials
or bearer tokens are persisted. Resolve an existing pending operation before
creating another one. If the server committed, recover the original result and
ledger without uploading the current (possibly edited) working file. If not,
retry the same immutable snapshot and original lease token. Do not silently move
a pending operation to a new checkout or substitute changed bytes.

Preparing/sending/reconciling uses existing workers; document operations remain
on the GUI thread. The operation remains recoverable across a timeout or process
restart. Local file edits during transfer remain local and are reported. Local
ledger and server commit cannot share a transaction; reconciliation must be
idempotent and retryable. No automatic fallback to legacy multi-request check-in
when the new endpoint is unavailable.

## Explicit limits and next increments

- File-system promotion and SQLite commit are not a distributed transaction.
  A crash/rollback after promotion can leave an unreferenced immutable blob;
  metadata must never expose a partial check-in. Orphan reconciliation remains
  later operational work. Existing storage fsync/platform limits remain.
- The server does not parse FreeCAD business objects. As with existing manifest
  APIs, CAD-reference capture is the adapter's responsibility. The addon only
  uses this increment for part documents whose saved-reference inspection is empty.
- Assemblies with pinned references, legacy write fencing, revision-creation
  idempotency, full recovery tooling and production hardening follow separately.
- Validation must include interrupted streams, hash mismatch, DB failure,
  permission/lease changes during upload, replay after a new checkout, key
  collisions and concurrent worker/process requests. No user CAD data is used
  for destructive tests.

## Increment 2 — 2026-11-02

The user authorized continuing Phase 5. Extend the same transaction/replay boundary
to supported assemblies and external-reference parts. Normalize and fingerprint
the full manifest; validate exact targets with current permissions in the final
transaction and insert all dependency rows before publishing. New datasets can
reference only existing datasets, so immutable edges cannot create a cycle through
the newly allocated dataset. Existing manifest attachment retains its cycle check.

Keep empty-manifest fingerprints and prior journal records compatible. Persist
pins with the original snapshot and acknowledge only after the returned server
manifest matches. Nonempty manifests use a new explicit HTTP route to avoid old
servers silently ignoring an unknown multipart field. CAD capture remains the
adapter's responsibility; BOM synchronization stays separate. Legacy write fencing
and revision-creation retries remain subsequent increments.

## Increment 3 — 2026-11-12

Legacy-write fencing, recoverable revision creation and read-only recovery
diagnostics are implemented in [ADR-019](ADR-019-phase5-write-fencing-and-revision-recovery.md).
Its explicit protected routes and coordinated backend/addon upgrade supersede
the initial legacy-client compatibility allowance above.
