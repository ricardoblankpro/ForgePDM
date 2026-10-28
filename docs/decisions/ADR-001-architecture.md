# ADR-001: Backend-First Modular Monolith

- **Status:** Accepted
- **Date:** 2026-10-27

## Context

The repository contains a legacy FreeCAD PDM specification and standalone macros. They demonstrate useful numbering, revision, checkout, BOM, search, and file workflows, but persist authority in several JSON files and CAD-folder paths. The macros mix FreeCAD UI, domain logic, and direct file access. ForgePDM needs reliable transactions, integrity checks, concurrency protection, and future multi-user/API access without starting with enterprise-scale deployment complexity.

EasyPDM demonstrates a practical service/API plus database and CAD-client pattern for small teams. Teamcenter supplies useful conceptual distinctions between Items, revisions, attached datasets, product structures, and lifecycle control. Neither is a blueprint: EasyPDM's current stack and broader feature set differ, and Teamcenter's enterprise workflows/configuration are outside ForgePDM's MVP.

## Decision

Propose a Python modular monolith with a versioned HTTP API, application services, a framework-independent domain layer, SQLite metadata persistence with migrations, and a separate immutable local file store addressed by content hash. FreeCAD will be a thin client. PostgreSQL and remote/object storage remain infrastructure adapters enabled by later deployment requirements.

Metadata operations are transactional. File bytes are staged and verified before metadata association; storage keys are server-generated; check-in associates immutable content and closes checkout in one metadata transaction. Enforce unique numbering and one active checkout using database constraints, optimistic version checks, and audited recovery. Store BOM references to explicit ItemRevision IDs to retain historical structure.

API identity uses password verification and opaque random bearer tokens. Only token hashes are stored; tokens expire and can be revoked. Global administrator role and per-project owner/editor/viewer memberships provide the initial authorization boundary. Deployment hardening and abuse controls remain follow-up work.

## Consequences

**Benefits:** small local deployment; clear seams for testing and future adapters; no FreeCAD dependency in business rules; database-enforced identity/concurrency; files can be verified and backed up separately.

**Costs and limits:** filesystem/database operations are not one atomic transaction, so staging, reconciliation, and orphan cleanup are required. SQLite limits write concurrency and is not the multi-host production target. An HTTP API and schema migrations add initial setup work compared with direct shared-folder macros.

## Alternatives considered

- **Continue with shared-folder JSON:** simplest for a single user, but unsafe for concurrent updates and weak for transactions, querying, and authorization.
- **FreeCAD-only macro application:** convenient UI integration, but couples domain behavior to FreeCAD and makes API reuse and headless tests difficult.
- **Microservices:** separate services could scale independently, but add deployment and consistency complexity before ForgePDM has proven scale requirements.
- **Start with PostgreSQL and broad PLM workflows:** stronger multi-user foundation, but more operational burden than required for the local/small-team MVP. Keep migrations and repository boundaries to make a later move viable.

## References

- [EasyPDM repository](https://github.com/pawelcel/EasyPDM) and [technical documentation](https://github.com/pawelcel/EasyPDM/blob/main/TECHNICAL.md)
- [Siemens Teamcenter BOM management](https://www.siemens.com/en-us/products/teamcenter/solutions/bom-bill-of-materials-management/)
- [Siemens Teamcenter document management](https://www.siemens.com/en-us/products/teamcenter/solutions/document-management/)

## Approval

Approved by the project owner on 2026-10-27. Implementation may proceed within this decision's boundaries. Detailed policy questions listed in the architecture and domain model documents remain open and should be resolved before production use.
