# ForgePDM

ForgePDM is a backend-first product data management system for engineering teams, with FreeCAD as its first planned CAD client. The current increment provides a local FastAPI service, password login, bearer sessions, project access roles, SQLite-backed Items/revisions/datasets, and SHA-256 content-addressed file storage. Checkout, BOM, release workflows, and the FreeCAD client are planned follow-on work.

## Local development

Requires Python 3.11+ and `uv`.

```sh
uv sync --group dev
uv run forgepdm create-user admin "Admin User" --role admin
uv run forgepdm create-user alice "Alice Example"
uv run forgepdm create-project PRJ-001 "Prototype Project"
uv run forgepdm grant-project PROJECT_UUID ALICE_UUID --role editor
uv run uvicorn forgepdm.main:app --app-dir src --reload
```

The CLI prompts for a password when creating a user and prints generated UUIDs. Use the project UUID as `project_id` when creating an item. Log in at `POST /api/v1/auth/login`, then pass its bearer token to protected API routes. Passwords are hashed with scrypt; bearer tokens are random opaque values stored only as SHA-256 hashes and expire after eight hours. Global admins can access all items. Other users need project membership (`owner`, `editor`, or `viewer`); only owners/editors can create or edit items in that project. Projectless items are admin-only. Accounts created before authentication was added have no password; set one with `uv run forgepdm set-password USERNAME` and grant admin role locally if needed with `uv run forgepdm set-role USERNAME admin`.

Example request (replace the UUID placeholders with CLI output):

```sh
curl -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"your password"}'
```

Use the returned `access_token` as `Authorization: Bearer TOKEN` on `/api/v1/items`. Use `forgepdm set-password USERNAME` to reset a local account's password; this revokes its active sessions. `forgepdm set-role USERNAME admin` assigns the global administrator role. The database defaults to `var/forgepdm.sqlite3`; set `FORGEPDM_DATABASE` to use another path. `/health` reports service availability. API details are exposed by FastAPI's local `/docs` page.

New items are automatically checked out to their creator for eight hours. Older Working revisions without a checkout can acquire one with `POST /api/v1/revisions/{revision_id}/checkout`. To attach a file to a checked out Working revision, use `POST /api/v1/revisions/{revision_id}/datasets` with multipart fields `file`, `dataset_type` (`native_cad`, `drawing`, `neutral`, `document`, or `other`), and optional `name`. List attachments with `GET /api/v1/revisions/{revision_id}/datasets` and download a file from the returned `download_url`. Check in with `POST /api/v1/revisions/{revision_id}/checkin` and body `{"change_note":"Initial design complete"}`, then release it with `POST /api/v1/revisions/{revision_id}/lifecycle` and body `{"target":"released"}`. A released item can get its next revision through `POST /api/v1/items/{item_id}/revisions` with a change note; the new revision is automatically checked out to its creator. Checkouts can also be renewed, inspected, or released through the `/api/v1/revisions/{revision_id}/checkout` routes. Admin override releases require a reason.

For an assembly, replace its Working revision BOM using `PUT /api/v1/revisions/{revision_id}/bom` with `{"lines":[{"component_revision_id":"UUID","quantity":2,"position":1}]}`. Every line points to a specific component revision. `GET /api/v1/revisions/{revision_id}/bom?recursive=true` returns its nested structure, and `GET /api/v1/items/{item_id}/where-used` finds assemblies that use an item. Cycles are rejected, and an assembly can be released only after its direct component revisions are Released. A new assembly revision copies its previous BOM lines.

Uploads default to a 1 GiB limit; configure `FORGEPDM_MAX_UPLOAD_BYTES` to change it and `FORGEPDM_FILE_ROOT` to change the blob directory. The server hashes uploads, stores them under generated hash paths outside SQLite, and verifies size and hash before download.

Keep the server bound to loopback. Authentication is now implemented, but transport security, login rate limiting, production secret/backup operations, and a security review are still outstanding; do not expose this early service to an untrusted network or use sensitive production data yet.

## Project map

- `src/forgepdm/domain/`: framework-independent entities and domain errors.
- `src/forgepdm/application/`: use cases.
- `src/forgepdm/infrastructure/`: SQLite adapter.
- `src/forgepdm/api/v1/`: versioned HTTP routes.
- `references/legacy/`: historical FreeCAD prototype and specification; preserve unchanged.
- `docs/`: architecture, domain model, roadmap, and decisions.

Run `uv run ruff check src` and `uv run ruff format --check src` for style checks.

Run the automated backend suite with `uv run --group dev pytest -q`. Tests use temporary SQLite databases and file stores.
