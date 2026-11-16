# Roadmap

The [current handoff](../../DEVELOPMENT_STATUS.md) owns delivery versions and
recent verification. Earlier phase numbering and implementation plans are
[historical records](../history/README.md), not a second active roadmap.

## Delivered

- Backend identity, projects/library permissions, permanent codes and revision history.
- Immutable file storage and exact CAD dependency manifests/workspaces.
- Fenced checkout/check-in, lifecycle, recoverable revision creation and diagnostics.
- Standard/purchased parts, Fasteners association, descriptions and mass evidence.
- Persistent FreeCAD browser, local shortcuts and scoped web administration.
- Shared Direct/Indented/Flattened reports and customizable TechDraw tables/PDFs.

## Next work, selected by user priority

| Area | Remaining scope |
|---|---|
| Contributor/release preparation | Clear current docs, portable validation, stable distribution source, owner-approved licensing/contact, clean startup and platform evidence |
| Operations | Automated backup/verified restore, production security, wider multiuser/failure acceptance and controlled garbage collection |
| Drawings | Sheet splitting, balloon integration, CAD-property columns and publication freshness gates |
| Browsing | Shared immutable CAD thumbnails; see the [proposal](plans/thumbnails.md) |
| Integrations | Broader supplier coverage and explicitly mapped ERPNext synchronization |

Stock/cutting optimization, workflow designers, effectivity/variants, general
multi-CAD support and PostgreSQL production deployment remain separate increments.
No next feature order is assumed. Code refactors, such as splitting large command
or route modules, should be isolated from behavior changes and preserve all
compatibility/data contracts.
