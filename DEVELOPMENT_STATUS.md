# Development status

This is the current handoff. Earlier implementation chronology and test counts
are in [the historical log](docs/history/development-log.md), not current setup
instructions. Start with [README](README.md) and [Contributing](CONTRIBUTING.md).

## Delivery

- Addon: **0.19.1**
- Backend package: **0.1.0**
- Database schema: **17**

The backend, addon and schema are independently versioned. Repository cleanup
changes documentation, packaging and contributor tooling; PDM rules and supported
engineering data formats remain unchanged. The owner selected AGPL-3.0-or-later
for the server and LGPL-2.1-or-later for the Workbench, with
ricardoblankpro@gmail.com as public maintainer contact. An
installable Addon Manager distribution source/publication remains a separate step.

## Current behavior

- FastAPI/SQLite metadata, separate immutable SHA-256 files, password/bearer
  sessions and project/shared-library permissions.
- Permanent P/A/S/M codes, exact revisions, exclusive leases, lifecycle and audit.
- Managed FreeCAD workspaces and exact revision/dataset/file/object manifests.
- Atomic native part/assembly check-in, fenced writes, replayable revision
  creation and read-only integrity/recovery diagnostics.
- Shared S/M catalog, Fasteners association, P/A/M descriptions, optional physical
  material snapshots and P/S mass evidence.
- Persistent FreeCAD browser with local Recent/Favorites/My Checkouts; web
  browsing, description controls and account/project administration.
- One backend report for Direct/Indented/Flattened BOMs and mass. Root quantities
  and exact pins are preserved; CAD synchronization stays an explicit reviewed
  direct-BOM replacement.
- TechDraw BOMs have editable titles, layouts/custom notes and no generated
  footer. Direct tables use format 1; non-direct use format 2. Saved tables stay
  frozen until explicit Update. PDF publication pins an exact uploaded source.

## Validation and local installation

The CI Qt job explicitly installs Ubuntu EGL/GL/OpenGL libraries and sets
`QT_QPA_PLATFORM=offscreen`. The initial hosted run lacked `libEGL.so.1` and failed
during Qt import; backend/docs and addon jobs passed. The correction passes all
19 Qt tests locally; hosted results are recorded in GitHub Actions.

Repository cleanup passes 264 backend tests, 411 addon tests (four optional Qt
modules skipped in the base environment), 19 real Qt checks and five Node test
files. Source/tooling and addon lint/format, documentation targets/anchors/version
checks, deterministic archive/self-contained docs, wheel/sdist and checksums pass.
Chrome passes 26 browsing, seven materials and 13 shared-report checks. Relocated
native harnesses pass 21 drawing/viewer/PDF checks plus the 28-check atomic seed.
These use disposable fixtures; three open user documents and the session survive.

Install 0.19.1 into both FreeCAD profiles after consistent SQLite/blob/prior-addon
backup under `var/backups/before-repository-cleanup-20261115T235426Z`. All 39 table
contents and 213 stored-file hashes are preserved; integrity/FKs pass. Both
profiles match the archive; the running FreeCAD package reports 0.19.1. Backend
APIs/schema are unchanged and the production backend was not restarted. All
schema/migration definitions compare unchanged with the preceding commit.

See [cleanup evidence](docs/validation/README.md#repository-cleanup) and
[earlier functional evidence](docs/validation/README.md#shared-bom-functional-baseline).
The eight canonical user guides are packaged from source; no duplicate manual is
maintained. Original prototype inputs were removed, old plans/logs archived,
native harnesses consolidated, and artifact creation automated without publication.
The explicit backend lint baseline checks E4/E7/E9/F/I; broader policy changes and
large command/route refactors remain separately reviewed work.

Native acceptance has used Linux FreeCAD 1.1.4 / Python 3.11.14 / Qt 6.8.3.
Other runtime/platform combinations remain unverified. Never infer current open
files, checkout/session state or runtime version from an older report.

## Current limits and next priorities

- Production security, automated backup/verified restore, automated garbage
  collection and wider multiuser/platform/clean-start acceptance remain open.
- TechDraw tables are bounded to 500 rows and one page. Sheet splitting,
  balloons, CAD-property mappings and automatic stale-publication gates remain.
- Shared thumbnails, broader supplier coverage, stock/cutting workflows and
  ERPNext synchronization are unimplemented. Select feature order with the user.
- Advanced material-input APIs/records remain supported compatibility surfaces,
  although the ordinary UI uses descriptions. Preserve migrations and old-file
  retrieval/recovery contracts during cleanup.

Follow [the roadmap](docs/development/roadmap.md), [release prerequisites](docs/development/releasing.md)
and [test tiers](docs/development/testing.md). Keep local documents/edits,
workspaces, credentials, checkouts and engineering data intact. Update this brief
handoff after significant changes; move chronology to history rather than growing
another installation diary.
