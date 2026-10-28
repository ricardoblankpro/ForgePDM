# ForgePDM — Development Instructions

## Project mission

Build ForgePDM, an open-source-oriented Product Data Management system with FreeCAD as its primary CAD client.

## Architectural references

- Siemens Teamcenter: conceptual reference for Item, ItemRevision, Dataset, BOM, Lifecycle and revision management.
- EasyPDM: https://github.com/pawelcel/EasyPDM — practical reference for CAD/PDM integration and workflows.
- Existing FreeCAD PDM specification and legacy macros located in `references/legacy/`.

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

- Inspect existing code before making changes.
- Propose a plan before major architectural changes.
- Implement small, testable increments.
- Write automated tests for domain logic.
- Do not silently change established PDM rules.
- Document important architectural decisions.
- Never delete or overwrite legacy reference files.
- Do not copy third-party source code without checking its license.

## Initial development priorities

1. Review legacy implementation and EasyPDM.
2. Define the domain model and architecture.
3. Create the backend project structure.
4. Implement Item and ItemRevision.
5. Implement file storage and datasets.
6. Implement check-in/check-out and lifecycle.
7. Create the FreeCAD Workbench client.

## Language

Documentation and explanations may be in Portuguese. Code identifiers, API names and technical comments should be in English.
