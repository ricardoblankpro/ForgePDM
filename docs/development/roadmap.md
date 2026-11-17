# Roadmap

The [current handoff](../../DEVELOPMENT_STATUS.md) owns delivery versions and
recent verification. Earlier phase numbering and implementation plans are
[historical records](../history/README.md), not a second active roadmap.

## Delivered

- Backend identity, projects/library permissions, permanent codes and revision history.
- Immutable file storage and exact CAD dependency manifests/workspaces.
- Fenced checkout/check-in, lifecycle, recoverable revision creation and diagnostics.
- Standard/purchased parts, Fasteners association, descriptions and mass evidence.
- Reviewed en/pt-BR item descriptions, original fallback, multilingual search and frozen localized BOMs.
- Persistent FreeCAD browser, local shortcuts and scoped web administration.
- Shared Direct/Indented/Flattened reports and customizable TechDraw tables/PDFs.
- Online SQLite/blob backups, isolated verified restore, Linux scheduling and stale-run status.
- Shared isometric previews for exact new CAD snapshots in FreeCAD and web browsers.
- Canonical documentation, portable validation harnesses, release artifact tooling
  and owner-approved licensing/contact boundaries.

## Next work, selected by user priority

| Area | Remaining scope |
|---|---|
| Contributor/release preparation | Stable Addon Manager distribution source, fresh-profile/clean-start acceptance and broader platform evidence |
| Operations | Off-device backup policy, retention/alerts, disaster-cutover acceptance, production security, wider multiuser/failure acceptance and controlled garbage collection |
| Drawings | Sheet splitting, balloon integration, CAD-property columns and publication freshness gates |
| Browsing | Explicit preview backfill, per-row lazy loading and broader rendering/platform acceptance |
| Integrations | Broader supplier coverage and explicitly mapped ERPNext synchronization |

Stock/cutting optimization, workflow designers, effectivity/variants, general
multi-CAD support and PostgreSQL production deployment remain separate increments.
No next feature order is assumed. Code refactors, such as splitting large command
or route modules, should be isolated from behavior changes and preserve all
compatibility/data contracts.
