# Automated backups and verified restore

Online SQLite/blob backups, integrity verification, new-directory restoration and
isolated restore drills are available since backend 0.1.1. See the
[current handoff](../../DEVELOPMENT_STATUS.md#delivery) for installed versions.
The implementation targets local SQLite/immutable-file storage; it is not a
PostgreSQL backup adapter. Linux user timers provide scheduling; the backup CLI
does not require FreeCAD or the addon to be running.

## What a backup contains

Each private `backup-TIMESTAMP-ID/` directory contains:

- `database.sqlite3`: a consistent standalone snapshot made with SQLite's online
  backup API, including committed WAL contents. Uncommitted transactions are excluded.
- `files/sha256/...`: every immutable blob referenced by that snapshot, deduplicated
  by hash, including historical datasets, published PDFs and thumbnail derivatives.
- `manifest.json`: format/database-engine identifiers, snapshot start/end bounds,
  completion timestamp, backend/Python/SQLite versions, schema versions, table counts
  and database/blob hashes and sizes.

Creation verifies SQLite integrity, foreign keys, supported schema, manifest parity
and every copied file hash before publishing a complete directory. Files are
copied independently, not hard-linked to live storage. Interrupted/incomplete
directories are never selected as completed backups. A failing newest completed
backup causes an error; automatic drills never silently select an older generation.

This is a server-data backup, not a check-in or workstation backup. Open/unsaved
FreeCAD edits, managed workspaces, local operation journals, preferences, material
cards, installed addons, configuration secrets and software artifacts are not
included. Preserve those separately. Keep compatible backend/addon release artifacts
and their lockfiles available; a recorded version is not an embedded installer.
Unreferenced/staging blobs are excluded and are not deleted from live storage.

Online consistency depends on the current storage contract: promote durable blob
bytes before committing their database reference; never change/delete committed
blob bytes. A future garbage collector must coordinate with backup readers before
deleting blobs. See [ADR-024](../decisions/ADR-024-backup-and-restore-automation.md).

## Create, inspect and drill

Run from the configured server working directory, with the same
`FORGEPDM_DATABASE` and `FORGEPDM_FILE_ROOT` as the server:

```sh
uv run forgepdm backup-create --destination var/backups/automated
uv run forgepdm backup-verify var/backups/automated/BACKUP_DIRECTORY
uv run forgepdm backup-drill var/backups/automated --latest --scratch-root var/restore-drills
uv run forgepdm backup-status var/backups/automated
```

`backup-create` and `backup-drill` record JSON status in the backup repository.
They share a nonblocking interprocess lock; overlapping commands fail clearly.
Reports retain the last successful result when a subsequent attempt fails, and
mark an interrupted run as incomplete. `backup-status` exits nonzero for missing,
failed or stale runs; defaults are three hours for backups and 48 hours for drills.
Use `--max-age-hours` and `--max-drill-age-hours` for another schedule.

The drill verifies the source bundle, restores into a newly created disposable
directory, verifies the restored database and every file, then removes only that
disposable copy. It never starts a public server, changes leases, revokes sessions,
uploads a file or saves a FreeCAD document. Automated drills establish structural
recoverability, not complete GUI/platform acceptance. Tests additionally exercise
authentication, authorization, historical BOM/manifest reads and file retrieval
through an API running against a restored disposable fixture.

Backup repositories and drill storage must be separate from one another and from
live data. Symlinks, path overlap and restoration into existing directories are
rejected. Private directories/files use modes 0700/0600. Backup verification is
read-only and performs no migrations. Unknown backup formats, database engines or
schema histories fail; known prior migration prefixes (including schema 17 before
thumbnails) remain verifiable/restorable without migrating the archive. Use
compatible software for startup and retain the original archive unchanged.

## Enable Linux scheduling

Install the current backend into its environment first (`uv sync --group dev --locked`).
Review generated unit definitions without changing the machine:

```sh
uv run python tools/install_backup_automation.py \
  --database var/forgepdm.sqlite3 --files var/files \
  --backups var/backups/automated --scratch var/restore-drills
```

Repeat with `--install` to write the user units and enable both timers. The installer
uses absolute paths and the installed environment's `forgepdm` executable. It does
not modify unrelated units; previously managed units retain `.previous` copies.

- `forgepdm-backup.timer`: hourly, with up to five minutes of randomized delay.
- `forgepdm-restore-drill.timer`: daily at 03:15 local time, with up to five minutes
  of randomized delay. Both timers catch up missed calendar events when activated.

Start the initial backup and drill sequentially, then inspect their results:

```sh
systemctl --user start forgepdm-backup.service
systemctl --user start forgepdm-restore-drill.service
systemctl --user list-timers forgepdm-backup.timer forgepdm-restore-drill.timer
uv run forgepdm backup-status var/backups/automated
journalctl --user -u forgepdm-backup.service -u forgepdm-restore-drill.service
```

Timers run while the user systemd manager is running. A sleeping/offline computer
cannot create hourly snapshots; catch-up creates a new current snapshot, not the
missed historical states. Unattended operation after logout requires separately
configured user lingering or a service deployment. Failures appear in service
status/journals and JSON reports; desktop/email alerts are not configured.

To disable scheduling without deleting backups:

```sh
systemctl --user disable --now forgepdm-backup.timer forgepdm-restore-drill.timer
```

There is no automatic retention/deletion policy in this increment. Monitor space;
each generation is a full independent copy. Creation/restoration requires space
for the referenced bytes plus a 64 MiB reserve and fails on I/O errors. The local
default is on the same drive as live data: it protects against logical failures,
not drive loss, theft or fire. Copy completed verified bundles to separately
managed storage and verify them there. No off-device destination is inferred or
mounted automatically. Hashes detect accidental corruption, not malicious rewriting
of both data and manifest; encryption and signed/offsite storage remain separate.

## Restore for an actual recovery

Keep the original backup untouched. Restore into a NEW directory:

```sh
uv run forgepdm backup-restore var/backups/automated/BACKUP_DIRECTORY \
  --destination var/recovered-server
```

The command refuses existing/live/overlapping targets, even when a target is empty.
It copies and verifies before completion and never automatically switches the
running service. Once a restored database has been started and changed, its old
backup manifest no longer describes its runtime bytes; retain the original bundle
for future verification/restoration.

For cutover, stop the old backend and all writers first. Preserve any newer live
data, workspaces and local journals, then explicitly configure the compatible server
to use `var/recovered-server/database.sqlite3` and `var/recovered-server/files`.
Keep it on loopback and verify health, sign-in, project/library permissions, exact
historical assembly retrieval, BOMs and drawing publication before admitting writes.
Review restored checkout/session expiry and local journals: their saved values are
preserved, while wall-clock time has advanced. Do not replay newer workstation
operations blindly against a rolled-back server. See [server recovery](server.md#recovery).
