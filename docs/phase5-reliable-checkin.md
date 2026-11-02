# Phase 5 — reliability implementation plan

The user approved beginning Phase 5 after the read-only web GUI. The first slice
is reliable check-in for a part with no external references; this does not mark
all of Phase 5 complete.

1. Introduce the additive operation record, fenced atomic part check-in and status
   API, preserving current PDM lifecycle, note and eight-hour checkout rules.
2. Test failures and concurrent requests against temporary databases/storage.
3. Add durable client snapshot/journal recovery and route eligible part check-in
   through the new operation. Keep assemblies explicitly on the existing path.
4. Validate retry/lost-response behavior and GUI-thread/worker boundaries in an
   isolated live FreeCAD/backend fixture. Document installed versions and limits.
5. Extend the protocol to assembly manifests and remaining legacy writes, then
   tackle revision-creation retry behavior and broader recovery acceptance.

See [ADR-008](decisions/ADR-008-atomic-part-checkin.md) for transaction boundaries,
replay semantics and the distinction between metadata atomicity and blob orphans.

## Implemented first increment — addon 0.6.0

- `POST /api/v1/revisions/{revision_id}/checkin-native`: multipart file plus
  `operation_id`, `expected_checkout_id`, `expected_checkout_version`,
  `content_hash`, `byte_size`, and optional `change_note`. The first increment
  accepts part revisions. The FreeCAD adapter additionally requires no saved
  external CAD references. Operation and lease IDs are UUIDs; SHA-256 is lowercase
  hexadecimal. Hash/size must match the actual uploaded bytes.
- `GET /api/v1/revisions/{revision_id}/checkin-operations/{operation_id}`: recover
  the original completed result, scoped to its actor and current read permission.
  Unknown/inaccessible operations return 404. The response includes the exact
  dataset/file IDs and original lease token. Check-in returns 200 on both first
  commit and replay; it never manufactures a second dataset for a completed key.
- SQLite migration 7 adds `checkin_operations`; it changes no existing items,
  revisions, files or checkouts. The local database was backed up before migration.
  Repeated migration and preservation of pre-existing datasets/leases are tested.
- Metadata transaction commits the file, dataset, empty manifest, note/audit,
  checkout release and operation result as one unit. Blob promotion precedes it;
  failed commits can leave safe unreferenced blobs, never partial metadata.

## Client use and recovery

Use the existing Check In command. Eligible parts use the new protocol; there is
no note prompt and omitted notes retain their previous value. Eight-hour leases
and existing lifecycle policies are unchanged. Assemblies and parts with external
references continue through the legacy upload/manifest/check-in workflow until
the next increment; they do **not** yet have the new atomicity/fencing guarantees.

Each working copy keeps a private `part-checkin.json` journal. A saved immutable
snapshot is retained until the server result and local ledger are acknowledged.
No password or bearer token is stored. Check In first resolves the prior operation,
before saving current edits or demanding a new lease. A lost response therefore
recovers the original snapshot, even if local edits have since been made. Those
edits remain local and the GUI explicitly reports that they were not included.

Uncommitted retries retain the same snapshot, operation ID and checkout token.
Renewing/reacquiring the lease invalidates that pending token. On a subsequent
Check In, the user can keep the pending snapshot or explicitly start a new
operation from the current document. Restart verifies the old operation did not
commit and its original lease is no longer valid, then archives its journal and
snapshot rather than discarding them. A committed operation must be recovered;
it cannot be abandoned into a duplicate check-in. A repeated completed check-in
without a new lease is an idempotent confirmation. A new owned lease permits a
new operation.

A rejected/failed or archived operation may retain local snapshots or promoted
server blobs for later cleanup. Recovery records are guarded against symlinks,
path escape, actor/revision changes and older workers overwriting a newer local
operation. Directory fsync is attempted where supported; power-loss guarantees
remain dependent on the OS/filesystem, as with the existing storage adapter.

## Validation

- Backend failure/contract tests cover atomic metadata/audit rollback, interrupted
  streams, SHA/size mismatch, upload limits, optional notes, replay and conflicting
  keys, replay after later checkout/release, final permission/lease checks and
  additive migration preservation.
- Two independent spawned processes race the same checkout. The same key returns
  one identical result to both; different keys allow one commit and one conflict.
- Client tests cover interrupted/lost responses, current edits, corrupted pending
  bytes, local ledger failure after server commit, another actor's journal,
  superseded local operations, explicit abandonment and unsupported old servers.
- The isolated live FreeCAD/HTTP harness passes 22 checks. It deliberately loses a
  successful response, edits the open document, recovers without duplicate upload,
  starts another leased check-in, interrupts a later transfer, renews that lease,
  verifies rejection and explicitly restarts from new current bytes. Source user
  documents/session are restored; all HTTP/file transfer work stays on workers.

Evidence: [live report](validation/phase5-atomic-part-checkin-2026-11-02.json).
The harness is `clients/freecad/tests/freecad_atomic_checkin_integration.py`, using
`freecad_phase4_smoke.py --serve CASE_DIR` for disposable authenticated backend
setup. Credentials stay in that private temporary fixture, never in this report.

## Remaining Phase 5 work

1. Extend atomic publication to assembly manifests and exact reference validation.
2. Fence remaining legacy dataset/manifest/check-in writes and review compatibility.
3. Make new-revision creation/retries recoverable without duplicate revisions.
4. Add broader interrupted-operation diagnostics and recovery/cleanup acceptance.
5. Expand multiuser/process and real assembly failure evidence. Backup/restore,
   security review and production distribution remain separate roadmap gates.
