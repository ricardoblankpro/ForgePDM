# ForgePDM documentation

Current delivery: **FreeCAD addon 0.15.0**, **backend SQLite schema 17**.
Start with [the project README](../README.md) and
[development handoff](../DEVELOPMENT_STATUS.md).

## Current user and deployment guides

- [Upgrade, backup, configuration and validation](upgrade-and-validation.md)
- [FreeCAD installation and workflows](../clients/freecad/README.md)
- [Standard Parts, shared library and Fasteners association](standard-parts.md)
- [P material / A assembly descriptions, native materials and part mass](material-management.md)
- [Supplier reference mass for S fasteners and CSV feeds](supplier-reference-mass.md)
- [Web management](web-management.md) and [web browsing/history](web-gui.md)
- [Source-pinned TechDraw PDF publication](drawing-pdfs.md)
- [Update from Server](update-from-server.md)
- [Component revision replacement](component-revision-replacement.md)
- [Native Assembly support](freecad-builtin-assembly.md)
- [Tree labels](freecad-tree-labels.md) and [tree status/description](tree-pdm-status.md)

## Architecture and delivery boundaries

- [Architecture](architecture.md), [domain model](domain-model.md) and [roadmap](roadmap.md)
- [Phase 5 reliability and recovery](phase5-reliable-checkin.md)
- [ADR-013: current simple descriptions](decisions/ADR-013-simple-material-and-assembly-descriptions.md)
- [ADR-014: native physical materials and part mass](decisions/ADR-014-physical-material-links-and-part-mass.md)
- [ADR-015: supplier reference mass](decisions/ADR-015-supplier-reference-mass.md)
- [ADR-016: CAD/manual S mass fallbacks](decisions/ADR-016-standard-part-mass-fallbacks.md)

Permanent P/A/S/M codes reuse one Item/revision system. ForgePDM owns engineering
metadata, CAD and revision-pinned BOMs. Stock, purchasing, costing and production
operations remain outside the prototype. Assembly mass aggregation, TechDraw BOM
tables, full supplier catalogs, cutting optimization and ERPNext synchronization
are not implemented.

## Historical plans and evidence

Phase 1–4 reports, the original [component catalog plan](component-catalog-plan.md)
and [S implementation sequence](../ForgePDM_Standard_Parts_Implementation_Plan.md)
record earlier delivered increments. Their version numbers, test counts and
stage-specific limitations are historical, not current installation instructions.
[ADR-012](decisions/ADR-012-item-master-and-material-inputs.md) records the advanced
material-input design superseded in the normal UI by ADR-013; its compatibility
APIs/data remain available.

Dated reports under `validation/` distinguish isolated automated/browser/native
checks from installation preservation checks. They are evidence of the recorded
runtime/date, not guarantees for untested platforms or future supplier responses.
Current limits and next-session instructions live in DEVELOPMENT_STATUS.md.

- [Assembly mass totals](assembly-mass.md): exact EBOM pins, source evidence and unknowns.
