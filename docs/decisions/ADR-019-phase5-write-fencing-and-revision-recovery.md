# ADR-019 — Complete Phase 5 write fencing and recoverable revision creation

Status: implemented, 2026-11-12. User authorized completing Phase 5.

## Checkout fencing

Ordinary dataset uploads, manifest attachment and legacy check-in require the
exact checkout UUID and positive version. Validate again in the serialized commit
transaction; upload captures its token before streaming/staging. Renewal changes
version and reacquisition changes identity, including reacquisition by the same
user. Ownership alone is insufficient. No automatic retry with a fresh token.

Public legacy routes require the token fields, rejecting older clients with 422.
The addon uses explicit `/datasets/fenced`, `/manifest/fenced` and
`/checkin/fenced` routes. These aliases have the same implementation as the
protected old routes. Explicit route names prevent old servers from silently
ignoring unknown fields. Coordinated backend/addon upgrade is required.

Ordinary upload plus manifest attachment remains two transactions; an interruption
can leave an uploaded native dataset without a manifest. Check In continues to
use the existing atomic native operation. BOM synchronization remains separate.

## Revision creation

Schema 17 adds actor-scoped `revision_operations`. A request supplies an operation
UUID, exact source revision and normalized nonblank note. Under one transaction,
check current source, permissions, Released lifecycle and checkout policy, create
the revision with existing copy-forward rules, acquire its checkout, audit and
save the original revision/checkout result. A same-key, same-intent retry returns
the original result without changing later checkouts or lifecycle. A different
intent conflicts. Status/replay require current read access; another actor cannot
retrieve an operation. Competing distinct keys against one source cannot create
successive unintended revisions.

The addon uses `/items/{id}/revisions/recoverable` and a private journal under
`$XDG_STATE_HOME/forgepdm/revision-operations` (default `~/.local/state`). Identity
includes server, actor, item and source revision. Save intent atomically before
HTTP. Reuse existing workspace locking/fsync and fail closed on corrupt or linked
journals. A status query resolves lost responses before retrying the original
intent. Journals contain no credentials and retain the prepared CAD-copy path.
The New Revision command recovers before its latest-Released guard or making a
second copy; it preserves open dirty target documents. Do not automatically
abandon an ambiguous operation or change its source/note.

Metadata creation and local CAD adoption/upload remain separate transactions.
A missing prepared copy is reported explicitly. Restore the retained copy, or
retrieve a published snapshot if one exists; a newly created revision need not
have a dataset yet. Retain journals/backups for manual diagnosis if local state
is damaged. Physical-material revision creation uses the same server protocol. Web description
controls use the same protected check-in and revision endpoints, preserving
credential-free intent in origin-scoped browser storage keyed by actor/item/source.
Web Locks serialize tabs when available; exact-source server checks prevent
duplicate next revisions even without browser lock support.

## Recovery diagnostics

`uv run forgepdm recovery-report` checks database integrity/foreign keys, verifies
all referenced file hashes/sizes, lists native datasets without manifests,
completed check-in/revision operation counts, staging files, unreferenced blob
candidates and symlinks. It does not delete or rewrite engineering data.

Stop the backend and other writers for an authoritative orphan inventory.
Live uploads can legitimately look unreferenced between promotion and commit.
Never delete candidates from a live report. Cleanup remains an offline,
backup-first administrator decision; do not remove shared/referenced blobs or
operation records used for replay. Fully automated garbage collection and
production backup/disaster recovery remain Phase 6 work.

## Acceptance boundaries

Require regression tests for changed/expired/reacquired leases during streaming,
missing-token API rejection, original replay after later checkout, intent
conflicts, permission revocation, transactional rollback, additive migration,
independent-process same/different-key races, durable client recovery after
response loss, and non-destructive corruption/orphan reporting. Native acceptance
uses only disposable CAD/backend data. Cross-platform and production operational
readiness remain separate gates.
