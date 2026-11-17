# ForgePDM documentation

Start with the [project overview](../README.md). [Development status](../DEVELOPMENT_STATUS.md)
is the single current handoff for delivery versions, recent verification and limits.

## User guides

| Guide | Covers |
|---|---|
| [Install the FreeCAD addon](user/install.md) | Requirements, package layout and connection |
| [FreeCAD workflow](user/freecad.md) | Browser, workspaces, checkout, check-in, release, revisions and tree labels |
| [Description languages](user/localization.md) | Source language, translations, approval and frozen documents |
| [Components](user/components.md) | Shared library, purchased models and Fasteners association |
| [Materials and component mass](user/materials.md) | P/A/M descriptions, physical materials and S mass sources |
| [BOMs and assembly mass](user/bom.md) | Direct/Indented/Flattened views, quantities and reviewed CAD synchronization |
| [Drawings and publishing](user/drawings.md) | TechDraw BOM tables, frozen values and PDF publication |
| [Web workspace](user/web.md) | Browsing, exact revision navigation and administration |
| [Troubleshooting](user/troubleshooting.md) | Common failures and safe recovery paths |

## Operations and development

- [Server setup, configuration, upgrades, backup and recovery](operations/server.md)
- [Scheduled backups and isolated restore verification](operations/backups.md)
- [Contributing](../CONTRIBUTING.md) and [test tiers](development/testing.md)
- [Architecture](development/architecture.md), [domain model](development/domain-model.md) and [API contracts](development/api.md)
- [Roadmap](development/roadmap.md), [release preparation](development/releasing.md) and [snapshot previews](user/freecad.md#snapshot-previews)
- [Fastener vocabulary research and provenance](development/references/fastener-options.md)

## Decisions and evidence

[Numbered ADRs](decisions/README.md) explain accepted decisions and superseded
approaches. [Validation reports](validation/README.md) are dated evidence, with
scope and runtime limitations. [Historical plans and development logs](history/README.md)
are retained separately from current instructions.
