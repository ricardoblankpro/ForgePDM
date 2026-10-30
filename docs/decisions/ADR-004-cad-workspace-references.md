# ADR-004: Managed CAD workspaces and immutable reference manifests

- Status: Implemented within the authorized Phase 3 scope
- Date: 2026-10-29

## Decision

Preserve the backend-first modular monolith, SQLite and existing domain rules.
Add migration 6 and an application manifest service, exposed through additive
`GET/POST /api/v1/datasets/{dataset_id}/manifest` endpoints. Existing databases,
file records and immutable blob bytes remain intact. The FreeCAD addon accesses
these identities only through HTTP; it imports neither the backend nor SQLite.

Each native dataset can receive one immutable manifest: source file ID, adapter
profile and occurrences binding a CAD object/property to an exact target
revision, dataset, file and target object. The server checks source edit rights,
active checkout ownership, native dataset membership, dependency read rights,
duplicate occurrences and dataset cycles inside its write transaction. A
conflicting second attachment fails; an identical replay is accepted only while
normal editing/checkout rules still permit writing. Reads enforce source and
direct dependency permissions; recursive retrieval rechecks every node.

These manifests describe serialized CAD dependencies. They do not replace the
engineering BOM. Teamcenter-style Item/Revision/Dataset/BOM separation remains;
FreeCAD occurrence links add client-specific reference identity. EasyPDM and the
legacy macros are references, not sources for authoritative client rules.

## Workspace and reconstruction

A workspace is bound to one normalized server URL, recorded without credentials.
It contains separate `working/<uuid>` copies, `configurations/<uuid>` retrievals,
and `.forgepdm` metadata, upload snapshots, staging and SHA-256 cache. Paths are
owned/generated rather than taken from uploaded filenames. A local exclusive
lock rejects concurrent clients; dead-owner recovery is restricted to the same
POSIX host and serializes recovery attempts. Unknown/remote owners, unreadable
locks and interrupted recovery guards require inspection. Network shares and
Windows lock recovery remain unverified.

Upload takes a stable, verified, read-only temporary snapshot. Child links must
refer to uploaded, unchanged managed files from the same server. New item
creation follows native-reference validation. Save As forks the working file;
refreshing whole-object links avoids FreeCAD 1.1's cached old relative paths.
Next Revision uses a separate working directory, preserving the previous file.

Retrieval selects an explicit revision and native dataset, walks its pinned DAG,
checks hashes and sizes even for cached files, and stages a new configuration.
It rejects missing dependencies and conflicting nonempty BOM revision sets.
It rewrites relative link paths in owned FCStd ZIP copies **before opening any
file**; merely downloading files or relinking after an uncontrolled open could
cause FreeCAD to load obsolete absolute paths. Cache/server blobs are untouched.
Children open first on the GUI thread. The adapter verifies exact document/object
identity and preserves placements. A complete ledger is written only after GUI
verification, save, hashing and local read-only protection succeed. Failures leave
no falsely complete configuration; retry uses a new directory and verified cache.
Dirty documents and existing configurations are never silently replaced.

## Supported profile and tradeoffs

`freecad-app-link-v1` supports whole-object external `App::Link.LinkedObject`
references, internal links and self-contained native files. Nested and repeated
occurrences are supported. Unsupported external subelements, cross-document
expressions, other external-link adapters and explicit external file/path assets
are rejected where recognized. Arbitrary third-party document proxies, texture
assets and Assembly workbench integrations are not certified by this profile.
Legacy files without manifests are accepted only when native inspection finds
no external dependencies. There is no fallback to an item's current revision.

Engineering BOM quantities, occurrence mapping and synchronization are Phase 4.
A nonempty existing BOM is checked for matching child revision sets, not occurrence
counts or quantities. An empty BOM is recorded as `not_synchronized`, not certified
as correct. Historical CAD retrieval pins exact bytes/links; it does not introduce
a frozen engineering BOM baseline or prevent existing permitted Working edits.

Upload, manifest attachment and check-in remain separate requests. Failure can
leave an unattached/manifestless dataset, and a timed-out mutation has an uncertain
outcome. No automatic mutation retry is introduced. Atomicity, fencing,
idempotency and lease policy belong to Phase 5. Local chmod protection is advisory;
server immutability and content hashes remain authoritative. Local ledgers are
not tamper-proof, and this is not a hostile filesystem security boundary.

No PostgreSQL migration, new distribution repository, BOM extraction, public
release, production deployment or deletion of legacy references occurs here.
