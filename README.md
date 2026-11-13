# ForgePDM

ForgePDM is a backend-first product data management system for engineering teams,
with FreeCAD as its primary CAD client. The current implementation provides a
FastAPI service, password/bearer authentication, project roles, SQLite-backed
Items/revisions/datasets/BOMs, exclusive checkout, lifecycle workflows and SHA-256
file storage. The independently packaged FreeCAD Workbench provides responsive
API workflows, authorized project/item browsing and historical revision selection.
Managed CAD workspaces reconstruct pinned assembly references, and the Workbench
can review and synchronize engineering BOMs for supported App::Link structures.
Its tree labels show item, pinned revision and persistent per-parent occurrence
numbers, with a refresh command for existing managed assemblies.
Atomic native check-in supports parts and supported assemblies. Further legacy-write
fencing and operational hardening remain in progress. TechDraw pages can be
explicitly published as source-pinned PDFs and viewed/downloaded in the web GUI;
see [drawing publication](docs/drawing-pdfs.md).

Current client: **0.12.0**; backend schema: **16**. The shared Item catalog uses
permanent `P000001`, `A000001`, `S000001` and `M000001` codes. Parts select a
raw-material description; assemblies use free text in the same tree Description
column. Optional native material links calculate finished part mass; supported S
fasteners can obtain supplier reference mass, CAD estimates or optional manual
mass when supplier data is unavailable. Assembly totals use the stored engineering
BOM and those published masses. TechDraw BOM tables and ERPNext synchronization
remain future work.

- [Material and assembly descriptions, physical materials and part mass](docs/material-management.md)
- [Standard Parts and Fasteners workflows](docs/standard-parts.md)
- [Supplier reference mass and supported families](docs/supplier-reference-mass.md)
- [Upgrade, backup and validation checklist](docs/upgrade-and-validation.md)
- [Documentation index and historical reports](docs/README.md)

See [Development status](DEVELOPMENT_STATUS.md) for the current handoff, recent
fixes, validation evidence and remaining work.

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

The CLI prompts for a password when creating a user and prints generated UUIDs. Use the project UUID as `project_id` when creating an item. Log in at `POST /api/v1/auth/login`, then pass its bearer token to protected API routes. Passwords are hashed with scrypt; bearer tokens are random opaque values stored only as SHA-256 hashes and expire after eight hours. Global admins can access all items. Other users need project membership (`owner`, `editor`, or `viewer`); only owners/editors can create or edit items in that project. Ordinary projectless P/A items are admin-only. S/M catalog items use the shared library; enabled readers can select them and library editors/admins can register them. Accounts created before authentication was added have no password; set one with `uv run forgepdm set-password USERNAME` and grant admin role locally if needed with `uv run forgepdm set-role USERNAME admin`.

Example request (replace the UUID placeholders with CLI output):

```sh
curl -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"your password"}'
```

Use the returned `access_token` as `Authorization: Bearer TOKEN` on `/api/v1/items`. Use `forgepdm set-password USERNAME` to reset a local account's password; this revokes its active sessions. Passwords require at least 4 characters; numeric passwords are allowed. Existing passwords remain valid. `forgepdm set-role USERNAME admin` assigns the global administrator role. The database defaults to `var/forgepdm.sqlite3`; set `FORGEPDM_DATABASE` to use another path. `/health` reports service availability. API details are exposed by FastAPI's local `/docs` page.

New items are automatically checked out to their creator for eight hours. Older Working revisions without a checkout can acquire one with `POST /api/v1/revisions/{revision_id}/checkout`. To attach a file to a checked out Working revision, use `POST /api/v1/revisions/{revision_id}/datasets` with multipart fields `file`, `dataset_type` (`native_cad`, `drawing`, `neutral`, `document`, or `other`), optional `name`, and required `expected_checkout_id` / `expected_checkout_version` from the checkout response. List attachments with `GET /api/v1/revisions/{revision_id}/datasets` and download a file from the returned `download_url`. Check in with `POST /api/v1/revisions/{revision_id}/checkin` and body `{"change_note":"Initial design complete","expected_checkout_id":"CHECKOUT_UUID","expected_checkout_version":1}`, then release it with `POST /api/v1/revisions/{revision_id}/lifecycle` and body `{"target":"released"}`. A released item can get its next revision through `POST /api/v1/items/{item_id}/revisions` with `operation_id` (a fresh UUID), `expected_source_revision_id` and a change note; retry with the same intent after a timeout. The new revision is automatically checked out to its creator. Checkouts can also be renewed, inspected, or released through the `/api/v1/revisions/{revision_id}/checkout` routes. Admin override releases require a reason.

For an assembly, replace its Working revision BOM using `PUT /api/v1/revisions/{revision_id}/bom` with `{"lines":[{"component_revision_id":"UUID","quantity":2,"position":1}]}`. Every line points to a specific component revision. `GET /api/v1/revisions/{revision_id}/bom?recursive=true` returns its nested structure, and `GET /api/v1/items/{item_id}/where-used` finds assemblies that use an item. Cycles are rejected, and an assembly can be released only after its direct component revisions are Released. A new assembly revision copies its previous BOM lines.

Check-in notes are optional: `POST /api/v1/revisions/{revision_id}/checkin` requires checkout ID/version and accepts
an optional `change_note` of up to 2000 characters. Omitting or
leaving the note blank preserves the existing revision note; the check-in is still
audited and releases the owned checkout. The FreeCAD check-in command does not
prompt for a note. Creating a new revision continues to require a change note.

Uploads default to a 1 GiB limit; configure `FORGEPDM_MAX_UPLOAD_BYTES` to change it and `FORGEPDM_FILE_ROOT` to change the blob directory. The server hashes uploads, stores them under generated hash paths outside SQLite, and verifies size and hash before download.

Keep the server bound to loopback. Authentication is now implemented, but transport security, login rate limiting, production secret/backup operations, and a security review are still outstanding; do not expose this early service to an untrusted network or use sensitive production data yet.

## Reliable native check-in

Addon 0.6.1 checks in parts and supported assemblies with one fenced, idempotent
operation. Native bytes, pinned reference manifest and checkout release publish
together. The operation status endpoint and private snapshot journal recover lost
responses without duplicate datasets or substitution of newer local edits.
Nonempty manifests use the explicit `checkin-native-with-references` route;
update/restart the backend together with the addon.

Addon 0.15.0/backend schema 17 also fence ordinary upload/manifest/check-in writes
and recover revision creation through durable actor-scoped operations. Upgrade
backend/addon together. `uv run forgepdm recovery-report` provides read-only
integrity and orphan diagnostics; stop writers before reviewing cleanup candidates.
See [transaction boundaries, API fields and recovery limits](docs/phase5-reliable-checkin.md).

## Web GUI

Open **http://127.0.0.1:8000/app/** while the backend is running. Sign in with the
same ForgePDM account used by the FreeCAD addon. No separate frontend server,
JavaScript dependency installation or build is required.

The workspace supports authorized project/item browsing, search,
revision history, direct/multilevel BOMs, where-used navigation and dataset file
downloads. BOM links open their exact recorded revisions. Newer revisions are
shown separately. The Description tab edits checked-out P/A/M descriptions and
material assignments; S entries show supplier reference mass and allow lookup
under an owned Working checkout. Administrators can import supplier reference CSV.
The browser does not replace CAD components or edit the engineering BOM.

Administrators can manage users, reset passwords, maintain project properties
(customer, due date and description), and assign project membership/roles. All
users can change their password, inspect their checkouts and browse scoped
activity history. New/reset accounts must change their temporary password before
accessing data. See [usage and an independent test checklist](docs/web-management.md).

Authentication tokens stay in page memory; refreshing the page requires sign-in.
Downloads retrieve individual dataset files. Use the FreeCAD addon to reconstruct
a complete assembly configuration with its pinned component files.

See [web GUI design, validation and limitations](docs/web-gui.md).

## Project map

- `src/forgepdm/domain/`: framework-independent entities and domain errors.
- `src/forgepdm/application/`: use cases.
- `src/forgepdm/infrastructure/`: SQLite adapter.
- `src/forgepdm/api/v1/`: versioned HTTP routes.
- `references/legacy/`: historical FreeCAD prototype and specification; preserve unchanged.
- `docs/`: architecture, domain model, roadmap, and decisions.

Run `uv run ruff check src` and `uv run ruff format --check src` for style checks.

Run the automated backend suite with `uv run --group dev pytest -q`. Tests use temporary SQLite databases and file stores.

## FreeCAD client and catalog reads

See [the addon README](clients/freecad/README.md) for installation and workflows.
The client requires a running backend; it does not install the server in FreeCAD.

Authenticated catalog endpoints are `GET /api/v1/projects`, `GET /api/v1/items`
(with `q` search text), `GET /api/v1/items/{id}/revisions` and
`GET /api/v1/revisions/{id}`. Paged reads accept `limit` (1–100) and non-negative
`offset`, returning `items`, `limit`, `offset` and `has_more`. Project selection
can request `editable=true`. Search filters project permissions before paging;
revision retrieval never silently substitutes the current revision for a
requested historical one. Existing write API contracts remain unchanged.

Standard/purchased parts and Fasteners integration: [usage and supported cases](docs/standard-parts.md).

Material descriptions, native physical links and finished part mass: [usage and API](docs/material-management.md). Advanced material-input/requirements APIs remain available for compatibility, but are hidden from the normal workflow.

Supplier reference mass: [workflow and coverage](docs/supplier-reference-mass.md).

Assembly mass: [totals and missing-component handling](docs/assembly-mass.md).
