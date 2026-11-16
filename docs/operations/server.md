# Server setup, upgrades and recovery

The FastAPI backend runs separately from FreeCAD and serves the web workspace.
The current supported topology is one local service with SQLite and a local
immutable file store. Production transport/security, automated backup/restore,
garbage collection and wider multiuser/platform acceptance remain open work.
Keep this development service on loopback until those deployment gates are met.

## First setup

From a source checkout with Python 3.11+ and uv:

```sh
uv sync --group dev --locked
uv run forgepdm create-user admin "Administrator" --role admin
uv run forgepdm create-project PRJ-001 "First project"
uv run uvicorn forgepdm.main:app --app-dir src --host 127.0.0.1 --port 8000
```

Create-user prompts for a password and prints IDs. Open
`http://127.0.0.1:8000/app/`. Admins can create users and grant project memberships
there. Alternatively create an ordinary account through the CLI and grant its
printed user UUID access to the printed project UUID:

```sh
uv run forgepdm create-user alice "Alice Example"
uv run forgepdm grant-project PROJECT_UUID ALICE_UUID --role editor
```

Bootstrap once; do not recreate users/projects on every startup. The local CLI
also provides `set-password USERNAME` (revokes active sessions) and
`set-role USERNAME admin`. Passwords currently accept at least four characters,
including numeric passwords. Preserve that established policy unless changing it
through an explicitly reviewed domain/security change.

`/health` checks service availability and `/docs` exposes the API schema.
`tools/open-web-gui.sh` is an optional Linux convenience launcher for an existing
local installation. It starts a loopback server only if needed and opens `/app/`.

## Configuration

Paths are resolved relative to the server working directory. Preserve existing
values when restarting or upgrading; a different root can look like an empty
installation.

| Variable | Default / purpose |
|---|---|
| `FORGEPDM_DATABASE` | `var/forgepdm.sqlite3` |
| `FORGEPDM_FILE_ROOT` | `var/files`, immutable SHA-256 storage |
| `FORGEPDM_MAX_UPLOAD_BYTES` | 1 GiB upload limit |
| `FORGEPDM_SUPPLIER_LOOKUP` | `1` enables bounded Fabory lookup; `0` retains CSV/manual/CAD sources without live requests |

Sessions are opaque bearer tokens, hashed in SQLite and normally valid for eight
hours. Project permissions and checkout ownership are enforced on the server.
FreeCAD/browser tokens stay in memory. Avoid credentials in URLs, documentation,
fixture reports and logs.

## Back up and upgrade

1. Preserve open CAD edits, managed workspaces and leases. A backup is not a
   check-in. Keep local FreeCAD preferences and native material snapshot cards.
2. Stop the backend and copy a consistent SQLite database together with its
   matching blob store. Include installed addon files and any SQLite WAL state
   or use SQLite's backup API. Retain the original matched set for rollback.
3. Update the source and sync locked dependencies. Inspect the current handoff
   and compatibility notes before starting a migrated database.
4. Build/replace the addon using [installation](../user/install.md). Keep the
   same server database/storage configuration. Start the backend, which applies
   unapplied migrations transactionally. Existing migrations are retained.
5. Check `/health`, sign-in, project/catalog access and an isolated upload/retrieval.
   Validate SQLite integrity and foreign keys. Refresh the web browser and restart
   FreeCAD after a normal addon replacement.

Backend package, addon and database schema are separate version identifiers;
see [current status](../../DEVELOPMENT_STATUS.md). Protected native operations
need their matching backend APIs even when no schema migration is added. The
shared BOM viewer requires `/api/v1/revisions/{id}/bom-report`. Older clients
cannot update non-direct format-2 drawing tables, but their SVG stays viewable.
Existing source CAD, tables and pins are not backfilled automatically.

## Recovery

With writers stopped, run:

```sh
uv run forgepdm recovery-report
```

This read-only diagnostic checks database/FK/blob integrity and reports incomplete
native uploads, staging/unreferenced candidates and completed operations. It
never deletes files or changes revision pins. Review candidates against an offline
backup before any manual cleanup; a live report cannot prove files are orphaned.

Preserve managed workspaces and local durable operation journals. Revision
journals live under `$XDG_STATE_HOME/forgepdm/revision-operations` (default
`~/.local/state/forgepdm/revision-operations`); other native/PDF journals belong
with their workspaces. They retain intent/snapshot evidence without credentials.
Retrying a command recovers the original operation; it does not publish newer
unsaved edits as an old result. Corrupt/lost local journals or prepared copies
need explicit inspection rather than guessed recovery.

Restore offline using matching database, blobs and compatible addon/backend
versions. Restoring only SQLite or running older code against a migrated schema
is not a supported rollback. Automated restoration drills remain a release gate.
