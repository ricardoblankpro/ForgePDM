# ForgePDM — Development Instructions

## Project mission

Build ForgePDM, an open-source-oriented Product Data Management system with FreeCAD as its primary CAD client.

## Architectural references

- Siemens Teamcenter: conceptual reference for Item, ItemRevision, Dataset, BOM, Lifecycle and revision management.
- EasyPDM: https://github.com/pawelcel/EasyPDM — practical reference for CAD/PDM integration and workflows.
- Prototype provenance and original-file pointers: `docs/history/provenance.md`. The inactive prototypes were removed after the approved repository audit.

Do not assume these references are identical. Document architectural differences and tradeoffs.

## Architecture principles

1. Backend-first, modular architecture.
2. Separate business logic from FreeCAD-specific code.
3. FreeCAD acts as a client of ForgePDM.
4. Support local development and future multiuser deployment.
5. Use Python as the primary programming language.
6. Prefer SQLite for the initial prototype, with a migration path to PostgreSQL.
7. Manage CAD files separately from database metadata.
8. Implement explicit transactions, file integrity checks and concurrency protection.
9. Design a stable API for future integrations.
10. Avoid unnecessary enterprise complexity in the MVP.

## Core domain entities

- Item
- ItemRevision
- Dataset
- File
- BOMLine
- Project
- User
- Checkout
- LifecycleState

## Development workflow

- Read `DEVELOPMENT_STATUS.md` at the start of a development session. Update it after significant changes with current behavior, validation evidence, known limitations and next steps; keep credentials and transient session details out of it.
- Inspect existing code before making changes.
- Propose a plan before major architectural changes.
- Implement small, testable increments.
- Write automated tests for domain logic.
- Do not silently change established PDM rules.
- Document important architectural decisions.
- Preserve database migrations, supported compatibility contracts, dated validation evidence and engineering data. Historical prototype inputs remain available in Git history.
- Do not copy third-party source code without checking its license.

## Repository and documentation

- Start at `README.md`, `CONTRIBUTING.md` and the concise `DEVELOPMENT_STATUS.md`.
- Current workflows belong in `docs/user/`, operations in `docs/operations/`, and
  contributor/API/release references in `docs/development/`. One guide owns each rule.
- Keep numbered ADRs and dated evidence; completed plans/chronology belong in
  `docs/history/`. Do not append new behavior below contradictory old instructions.
- User/operations guides are packaged from their canonical source; do not keep
  a duplicate installed manual. Run documentation and archive-link checks.
- The addon is versioned independently of the backend and schema. Preserve
  command IDs, exact revision/file pins, saved metadata and replay recovery.
- Respect approved licensing boundaries in `LICENSING.md`. Changing licenses or
  public contact, or publishing an Addon Index entry, needs an explicit owner
  decision. Preparing local artifacts is permitted.

## Language

Documentation and explanations may be in Portuguese. Code identifiers, API names and technical comments should be in English.
