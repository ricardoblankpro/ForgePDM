# ForgePDM Architecture Proposal

## Purpose and scope

ForgePDM is a backend-first PDM for small teams using FreeCAD as the first CAD client. The first implementation should be a Python modular monolith with a versioned HTTP API, a SQLite metadata database, and a separate filesystem object store. A modular monolith keeps deployment simple while preserving boundaries for a later PostgreSQL-backed multi-user service. FreeCAD is a client; domain rules must run on the backend and remain usable without FreeCAD installed.

## Components

- **API**: authentication boundary, request validation, stable versioned endpoints, and serialization. Start with FastAPI; do not put business rules in route handlers.
- **Application services**: use cases such as create item, create revision, check out, check in, attach dataset, release, and read BOM/where-used.
- **Domain**: entities, identifiers, lifecycle transitions, revision rules, and BOM constraints, independent of HTTP, SQLite, and FreeCAD.
- **Persistence**: repository interfaces with a SQLite implementation initially. Use database transactions and unique constraints for numbering and checkout ownership. Keep schema migrations from the first schema version to support PostgreSQL migration.
- **File storage**: store bytes outside the database under opaque content hashes; database `File` records hold hash, size, media type, original filename, and storage key. Verify hashes on ingest and retrieval. Never trust client paths as storage paths.
- **Clients**: the FreeCAD Workbench is a thin adapter that calls the API for metadata and transfers files through explicit upload/download endpoints. It keeps authentication in memory and stores item/revision identifiers in the document; domain rules remain on the server.

## Existing material assessment

The HTML specification contributes reusable business rules: sequential non-reused `P`/`A` numbers, revision-on-change-after-release, immutable released/archive content, one editor at a time, project organization, BOM quantities, search, and where-used. `PDM_NewItem.FCMacro` demonstrates item creation, naming, and metadata entry; `PDM_BOM.FCMacro` shows BOM spreadsheet output; `PDM_UpdateRelationships.FCMacro` extracts FreeCAD links; `PDM_SearchRetrieval.FCMacro` covers number/description/project and where-used searches; `PDM_UpdateVolume.FCMacro` shows a FreeCAD-derived property; `PDM_Login.FCMacro`/`PDM_Session.py` show a UI identity flow. Treat these as workflow examples, not reusable backend modules. Preserve the legacy files unchanged.

The implementation has concrete risks: hardcoded local PDM roots; JSON files acting as concurrent shared state; direct/non-atomic writes and no coordinated metadata/file transaction; schema shape inconsistencies across macros; labels and filenames parsed as identifiers; broad exception handling that hides errors; UI, FreeCAD access, validation, and persistence coupled together; and a session dialog that lets a user select/confirm a name rather than authenticate credentials. BOM extraction based on linked labels may miss structures not represented as `App::Link` and the relationship update overwrites assembly content from the active document. These patterns should not be carried into the backend.

Requirements needing product decisions include authentication method and roles; project/item access rules; numbering scope and migration of existing IDs; revision label policy; whether BOMs bind exact revisions or resolve latest; which files belong to a revision and their retention/deletion semantics; lifecycle permissions and approval; checkout expiry and admin recovery; backup/restore and supported storage topology; CAD version support; file size/type limits; and audit requirements. The proposed defaults below provide a minimal starting point, not settled policy.

## Transaction and consistency boundary

Metadata changes use one database transaction. File ingest is staged to a temporary file, hashed, then atomically placed in storage before its database reference is committed; failed metadata commits leave only reclaimable unreferenced blobs. Check-in records a new immutable file association with a revision and releases the checkout in the same metadata transaction. Use optimistic version checks for edits and a unique active-checkout constraint to prevent two writers. Record audit events for state-changing operations. A local filesystem store is the MVP adapter; network/object storage is a later adapter, not a domain dependency.

## Initial repository structure

```text
src/forgepdm/
  api/v1/                  # versioned HTTP routes and schemas
  application/             # use cases
  domain/                  # framework-independent entities and policies
  infrastructure/          # SQLite database and content-addressed file adapters
  main.py                  # FastAPI application factory
  cli.py                   # local user/project bootstrap
tests/                     # unit, service, and API integration coverage
clients/freecad/            # thin FreeCAD Workbench client
docs/
```

The current package uses FastAPI, Python's SQLite driver, and `uv` for dependency management. The Workbench lives in `clients/freecad/freecad/forgepdm/`, uses modern namespaced initialization and Python's standard-library HTTP client, and is packaged independently from the backend. See ADR-002 for packaging and manifest validation details. Keep `references/legacy/` read-only as historical input.

The initial implementation uses FastAPI with Python's SQLite driver, schema migrations, transactional Item plus initial ItemRevision creation, and audit events. Password login issues revocable, expiring opaque bearer sessions. Project membership roles gate item access, with a global administrator role. Revision scoped Dataset records refer to File metadata while immutable bytes live in a separate SHA-256 content addressed filesystem store. Uploads stage and hash content before promotion; download verifies stored bytes. Checkout is an eight-hour exclusive lease enforced by a partial unique index; check-in releases it, and file attachment and BOM edits require the lease owner. Released revisions are immutable, and creating the next revision also creates its initial checkout and copies forward the explicit-revision BOM. Assembly release requires direct BOM components to be Released. The FreeCAD Workbench is a thin API client and stores only item/revision identifiers in a hidden document object. A failed metadata commit can leave an unreferenced blob, so storage reconciliation/garbage collection remains future work. Transport security, login rate limiting, account recovery and production deployment hardening remain future work.

## References and tradeoffs

[EasyPDM](https://github.com/pawelcel/EasyPDM) provides a practical small-team precedent: one shared API/web service, database-backed metadata, and CAD macros that upload/download documents through the same service. ForgePDM adopts that separation while keeping its first client FreeCAD-focused and its MVP scope smaller; EasyPDM's current implementation uses .NET, PostgreSQL, and multiple CAD clients, so its source should not be copied without license review. [Teamcenter](https://www.siemens.com/en-us/products/teamcenter/solutions/bom-bill-of-materials-management/) informs the conceptual separation of item identity, revisions, attached datasets, structures, and lifecycle. ForgePDM deliberately excludes enterprise workflow, effectivity, variants, and multi-domain BOM configuration from the MVP.

## Risks and open requirements

The legacy design does not settle authentication strength, authorization granularity, retention/deletion policy, file size limits, backup/restore, revision conflict behavior, or BOM snapshot semantics. Resolve these before production use. SQLite is appropriate for local/small-team MVP use, but concurrent multi-user writes and network filesystem behavior require explicit limits and deployment guidance. A single-server deployment with a local disk is the initial supported topology.
