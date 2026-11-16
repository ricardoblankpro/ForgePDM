# ADR-024 — Consistent online backups and isolated restore drills

Date: 2026-11-16

Status: Accepted for the local SQLite pilot.

## Context

Metadata and immutable CAD bytes are stored separately and outside Git. Manual
pre-upgrade copies provide useful rollback evidence but do not establish scheduled
protection or repeatable recovery. A database-only copy cannot recover missing CAD
bytes; copying a live SQLite main file alone can omit committed WAL state.

## Decision

Add backend administration services and CLI commands rather than CAD commands or
an unauthenticated backup API. Use Python's SQLite online backup API to create a
closed, standalone snapshot first. Read its complete `files` table and copy/hash
every referenced immutable blob, deduplicating equal hashes. Publish a versioned
manifest and directory only after database/FK/schema and byte-integrity checks.
Private filesystem permissions and nonblocking process locking protect local runs.

The consistency argument relies on existing application ordering: durable blob
promotion precedes database commit, and committed hashes are immutable and not
garbage-collected. References committed after the snapshot are outside that recovery
point. Any future deletion/GC service must coordinate with active backup readers;
enabling concurrent uncoordinated GC would invalidate this protocol.

Restore only into a new, non-overlapping destination. Validate before and after
copying, never migrate the archive and never switch production automatically.
Daily drills use disposable isolated copies and preserve production documents,
leases, session records, manifests, operation receipts and exact revision/file pins.
Application-level disposable tests verify authentication/permissions and historical
BOM, manifest and file retrieval; structural scheduled drills do not certify all
GUI/platform or full disaster-cutover behavior.

Install opt-in Linux systemd user timers for hourly verified snapshots and daily
restore drills. Persist success/failure evidence and expose stale-run checks.
Retain every generation initially; automatic pruning, workstation backup,
off-device replication, encryption and notifications remain separately scoped.
Capture software versions but do not pretend that metadata embeds release artifacts.

## Alternatives and consequences

Stopping the server and copying the matched database/blob set remains valid, but
scheduled protection should not interrupt CAD clients or expire their workflows.
An ad-hoc live filesystem copy is rejected because it cannot establish WAL/database
consistency. SQLite snapshotting avoids introducing a general maintenance/write
gate into all existing APIs. PostgreSQL requires a separate capture/restore adapter;
`database_engine` and format version identify the supported contract explicitly.

Full independent copies cost space and I/O but avoid shared-hardlink corruption
and simplify isolated recovery. Local same-drive backups do not survive drive loss.
Checksums detect accidental corruption, not adversarial rewriting. Operator cutover
must reconcile newer workstation journals and leases with the restored recovery
point; no automated production rollback or silent rule changes are introduced.

## References

- [Operations contract](../operations/backups.md)
- [Python SQLite backup API](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup)
- [SQLite online backup design](https://www.sqlite.org/backup.html)
