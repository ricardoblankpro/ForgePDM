# ForgePDM MVP Roadmap

This roadmap sequences a backend-first MVP. Each phase includes focused automated
tests and actual integration evidence where available.

The phase numbering below records the original MVP sequence. The approved
development-direction roadmap now places **FreeCAD addon modernization in
Phase 1**. Its implementation and remaining acceptance gates are recorded in
[the Phase 1 report](freecad-addon-phase1.md) and
[ADR-002](decisions/ADR-002-freecad-addon-packaging.md).

## Active development-direction roadmap

**Current delivery: addon 0.10.0 / backend schema 16.** Simple P material/A assembly
descriptions, optional native density links and finished part mass, and bounded
S supplier reference mass are implemented. Current guides:
[materials](material-management.md), [supplier mass](supplier-reference-mass.md)
and [upgrade/validation](upgrade-and-validation.md). Assembly mass rollup,
TechDraw BOM tables, stock/cutting optimization and ERPNext synchronization remain
future increments; no new feature order is assumed without user direction.

**Standard/purchased component catalog delivered (originally addon 0.7.4).** Shared library
ownership replaces consuming-project assignment; registration skips the project
prompt, with reader/maintainer permissions (ADR-011). S-numbered
parts reuse ForgePDM Items, revisions, permissions and managed BOM/CAD workflows.
Fasteners integration resolves catalog associations during upload/check-in,
supports selected-occurrence reassociation and provides controlled specification
choices with generated uppercase catalog names. Purchased CAD models reuse managed
links. User pilot testing is in progress; supported cases and limitations are in
[standard parts](standard-parts.md), with the final sequence in
[the catalog plan](component-catalog-plan.md). Phase 5 reliability debt remains
tracked below; this feature does not mark Phase 5 complete.

| Phase | Scope | Status / next gate |
|---|---|---|
| 0 | Architecture review and governance | Baseline assessment and phase approvals recorded |
| 1 | Modern FreeCAD addon packaging | Implemented; live loading and part workflows tested |
| 2 | Initialization, connectivity and catalog browsing | Implemented; [scope and validation](freecad-addon-phase2.md) |
| 3 | Local workspace, CAD files and reference integrity | Implemented for supported whole-object App::Link and native AssemblyLink; [scope and validation](freecad-addon-phase3.md) |
| 4 | BOM extraction and revision-aware assembly synchronization | Implemented for direct parts/native subassemblies and reviewed replacement; [scope and validation](freecad-addon-phase4.md) |
| 5 | Robust checkout/check-in, lifecycle, revisions and datasets | Started: atomic part/assembly check-in with pinned manifests, fenced leases and durable replay implemented; legacy-write fencing and revision retries next |
| 6 | Security, testing, backup/recovery and operational hardening | Consolidate production-readiness evidence |
| 7 | Addon Manager distribution and stable deployment | Requires licensing, distribution approval and operational gates |
| 8 | Web interface, ERPNext and future integrations | Browsing plus user/password/project administration, my checkouts and scoped activity implemented locally; P/A/M descriptions/material assignment and S mass enrichment delivered; general CAD/BOM editing and ERP integration deferred |

The user approved bringing basic web browsing forward. Phase 5 remains the
backend reliability workstream; the component catalog above is delivered for
user pilot testing. The first web increment is served at `/app/`
and provides authorized project/item browsing, exact revision history, datasets,
where-used and direct/multilevel BOM views. User-approved account/project management, my checkouts and activity history
are now implemented; see [the functional GUI report](web-management.md). P/A/M description and material editing plus S supplier-mass enrichment are
implemented. General CAD/BOM editing, flattened BOM tools and ERP integrations
remain future work. See [the web GUI report](web-gui.md).

Phase 3 was explicitly authorized after Phase 2. Phase 4 provides reviewed,
revision-aware BOM synchronization for supported App::Link structures. The
original MVP sequence below is historical and uses different phase numbers.

## Phase 0 — decisions and project foundation (started)

- Confirm the architecture, entity boundaries, identifier policy, and open questions in these documents.
- Establish Python packaging, configuration, migration tooling, formatting/linting, and test conventions.
- Add a documented local development setup and CI checks.

**Exit:** a clean install can run the empty service and test suite reproducibly.

The architecture decision is approved. The package, versioned API, SQLite schema migrations, bootstrap CLI, password login, bearer sessions, project membership authorization, and Item plus revision A creation slice are in place. Dependency installation and the 16-test backend suite have been run successfully; CI setup remains outstanding.

## Phase 1 — metadata foundation

- Implement User, Project, Item, ItemRevision, and LifecycleState persistence and domain policies.
- Allocate unique item numbers transactionally; create initial Working revision A.
- Add versioned API operations for health, users/authentication foundation, projects, item creation, item/revision reads, and search by number/description.
- Add audit events for identity and lifecycle changes.

**Exit:** API and database tests prove numbering uniqueness, initial revision creation, and invalid transition rejection.

## Phase 2 — files and datasets (started)

- Implement staged file ingest, SHA-256 integrity checking, immutable local storage, and download authorization.
- Associate Dataset and File records with ItemRevision; support native CAD plus generic attachments.
- Add failure recovery/cleanup for staged or unreferenced files and document backup/restore.

**Exit:** integration tests prove hash/size verification, no path traversal, and consistent database references after failure.

Initial upload, revision attachment, listing, and authorized download endpoints are in place. Automated tests cover upload limits, staged-file cleanup, filename sanitization, hash verification, and authorized retrieval. Crash-orphan reconciliation remains outstanding.

## Phase 3 — controlled editing and release (started)

- Implement exclusive Checkout acquisition, renewal/release, stale checkout policy, and check-in transaction semantics.
- Create a new revision from a released revision and retain old file associations.
- Enforce lifecycle rules and audit all state-changing actions.

**Exit:** concurrency tests show only one active checkout per revision; released data cannot be mutated.

Initial lease acquisition/renew/release, check-in, Working → Released → Obsolete transitions, and next-revision creation are implemented. New Items and revisions automatically check out to their creator, and dataset upload requires that active lease. Tests cover lease conflicts, expired checkout reclamation, check-in/release, and revision progression; multi-process SQLite concurrency testing remains outstanding.

## Phase 4 — product structure (started)

- Implement BOMLine CRUD against explicit child revisions, quantities, positions, cycle detection, recursive BOM, and where-used queries.
- Add Project membership operations that do not imply ownership or deletion.

**Exit:** tests establish stable historical BOM results and correct project/item independence.

Direct and recursive BOM reads, atomic BOM replacement, explicit component revisions, cycle rejection, and where-used queries are implemented. Assembly release checks that all direct component revisions are Released; new assembly revisions copy the previous BOM. Tests cover cycle rejection, explicit revision references, where-used, BOM copy-forward, and component release gating.

## Phase 5 — FreeCAD client and pilot (started)

- Build a thin FreeCAD Workbench/client for login, item lookup/create, checkout/download, check-in/upload, and BOM display.
- Verify supported FreeCAD versions and real-world file transfer/recovery with pilot users.
- Document deployment, permissions, backup, upgrade, and data migration to PostgreSQL criteria.

**Exit:** end-to-end pilot can create, edit, release, revise, and retrieve an assembly and its exact component revisions.

The initial Workbench slice (historical) provided login, create/upload, checkout, check-in, release, next revision, recursive BOM display, and item/assembly download commands. Installation and workflow documentation is in `clients/freecad/README.md`. Native workflows have since been exercised in FreeCAD 1.1.4; supported pinned-link reconstruction is implemented. Current acceptance scope and remaining platform/operational gates are in DEVELOPMENT_STATUS.md and the Phase 3–5 reports.

## Not in MVP

Approval workflow designer, effectivity/configuration management,
alternate/substitute parts, full supplier/manufacturer catalog integrations beyond the delivered bounded reference-mass lookup,
notifications, client verification, multi-CAD clients, and PostgreSQL production
deployment remain deferred. A personal component catalog with basic supplier
metadata remains separate from the delivered component identity catalog; browser administration has already
been brought forward.
