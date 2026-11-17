# Architecture decisions

ADRs retain their numbered identities and original rationale. Some describe
superseded UI/planning stages; current behavior belongs in the [current
architecture](../development/architecture.md) and [user guides](../README.md).

| Decision | Record |
|---|---|
| 001 | [ADR-001: Backend-First Modular Monolith](ADR-001-architecture.md) |
| 002 | [ADR-002: Modern FreeCAD addon within the monorepo](ADR-002-freecad-addon-packaging.md) |
| 003 | [ADR-003: Responsive FreeCAD workflows and authorized catalog reads](ADR-003-freecad-connectivity.md) |
| 004 | [ADR-004: Managed CAD workspaces and immutable reference manifests](ADR-004-cad-workspace-references.md) |
| 005 | [ADR-005: Explicit engineering occurrences and reviewed BOM replacement](ADR-005-reviewed-bom-synchronization.md) |
| 006 | [ADR-006: Managed tree labels and persistent occurrence numbering](ADR-006-tree-occurrence-labels.md) |
| 007 | [ADR-007 — Isolate live CAD documents when creating revisions](ADR-007-live-revision-document-isolation.md) |
| 008 | [ADR-008 — Atomic part check-in with fenced leases and replay](ADR-008-atomic-part-checkin.md) |
| 009 | [ADR-009 — Explicit source-pinned drawing PDF publications](ADR-009-published-drawing-pdfs.md) |
| 010 | [ADR-010: S numbering and embedded Fasteners occurrences](ADR-010-standard-parts-and-fasteners.md) |
| 011 | [ADR-011 — Shared Standard Parts Library](ADR-011-shared-standard-parts-library.md) |
| 012 | [ADR-012: One Item Master and revision-bound manufacturing inputs](ADR-012-item-master-and-material-inputs.md) |
| 013 | [ADR-013: Simple material and assembly descriptions](ADR-013-simple-material-and-assembly-descriptions.md) |
| 014 | [ADR-014: Physical material links and source-pinned part mass](ADR-014-physical-material-links-and-part-mass.md) |
| 015 | [ADR-015: Supplier reference mass for Standard Parts](ADR-015-supplier-reference-mass.md) |
| 016 | [ADR-016: CAD estimate and manual S mass fallbacks](ADR-016-standard-part-mass-fallbacks.md) |
| 017 | [ADR-017: Derive assembly mass from the stored engineering BOM](ADR-017-assembly-mass.md) |
| 018 | [ADR-018 — Combined BOM review and display-only mass rounding](ADR-018-bom-review-and-mass-display.md) |
| 019 | [ADR-019 — Complete Phase 5 write fencing and recoverable revision creation](ADR-019-phase5-write-fencing-and-revision-recovery.md) |
| 020 | [ADR-020 — Persistent native browser and local shortcuts](ADR-020-native-browser-shortcuts.md) |
| 021 | [ADR-021 — Frozen direct engineering BOM tables in TechDraw](ADR-021-drawing-bom-tables.md) |
| 022 | [ADR-022 — Shared direct, indented and flattened engineering BOM reports](ADR-022-shared-bom-reports.md) |
| 023 | [ADR-023 — Current documentation and independent addon artifacts](ADR-023-repository-documentation-and-distribution.md) |
| 024 | [ADR-024 — Consistent online backups and isolated restore drills](ADR-024-backup-and-restore-automation.md) |
| 025 | [ADR-025 — Immutable isometric previews of exact CAD snapshots](ADR-025-immutable-isometric-thumbnails.md) |
| 026 | [ADR-026 — Versioned item description localization](ADR-026-versioned-item-description-localization.md) |

ADR-013 supersedes the ordinary advanced-input UI from ADR-012; its APIs/data
remain compatible. ADR-019 completes write fencing/revision recovery. ADR-022
extends the original direct drawing report to shared views. ADR-023 records
documentation and artifact organization. Never interpret an old phase status
as a current release gate without checking the current handoff.
