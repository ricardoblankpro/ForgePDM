# ForgePDM

ForgePDM is a Product Data Management system with FreeCAD as its primary CAD
client. A Python/FastAPI backend owns engineering metadata and permissions;
a separately installed FreeCAD Workbench manages CAD workflows. The backend
also serves the web workspace. SQLite metadata and immutable CAD bytes are
stored separately.

## What works

- Permanent P/A/S/M item codes, exact revisions, project permissions and audit history.
- Managed CAD workspaces, verified snapshot retrieval and pinned assembly references.
- Exclusive checkout, atomic native check-in, release and recoverable revision creation.
- Shared standard/purchased components, Fasteners association, materials and mass.
- Direct, Indented and Flattened BOM reports in FreeCAD, web and TechDraw.
- Customizable drawing BOM tables, linked Direct BOM balloons and explicit source-pinned PDF publication.
- Web browsing, description editing and account/project administration.
- Reviewed English/Portuguese item descriptions with original fallback and multilingual search.
- Shared isometric previews tied to exact uploaded CAD snapshots.
- Verified SQLite/CAD backups, isolated restore drills and Linux user scheduling.

See [current delivery and limitations](DEVELOPMENT_STATUS.md). This is a local
pilot: production hardening and Addon Index distribution are still pending.

## Start locally

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).
From the repository root:

```sh
uv sync --group dev --locked
uv run forgepdm create-user admin "Administrator" --role admin
uv run forgepdm create-project PRJ-001 "First project"
uv run uvicorn forgepdm.main:app --app-dir src --host 127.0.0.1 --port 8000
```

The CLI prompts for a password. Open [the web workspace](http://127.0.0.1:8000/app/)
with that account. Bootstrap only once; existing installations keep their users
and data. See [server setup and upgrades](docs/operations/server.md) and
[FreeCAD installation](docs/user/install.md) for the complete setup.

## Find your way

| Goal | Start here |
|---|---|
| Use FreeCAD or the web workspace | [User guides](docs/README.md#user-guides) |
| Install, upgrade, back up or recover | [Operations](docs/operations/server.md) |
| Contribute code or documentation | [Contributor guide](CONTRIBUTING.md) |
| Understand the system | [Architecture](docs/development/architecture.md) and [domain model](docs/development/domain-model.md) |
| See planned work or release requirements | [Roadmap](docs/development/roadmap.md) and [release guide](docs/development/releasing.md) |
| Inspect earlier decisions and evidence | [Architecture decisions](docs/decisions/README.md), [validation index](docs/validation/README.md), [history](docs/history/README.md) |

## Repository

`src/forgepdm/` contains the backend and web client. `clients/freecad/` contains
its independently packaged Workbench. Backend tests live in `tests/`; addon unit
and Qt tests live in `clients/freecad/tests/`. Native FreeCAD acceptance scripts
live in `clients/freecad/tools/validation/`. Runtime data, workspaces and generated
archives are excluded from Git.

The server is AGPL-3.0-or-later and the Workbench LGPL-2.1-or-later.
See [licensing boundaries](LICENSING.md) and the full [server license](LICENSE).
The original prototype is retained in Git history; its provenance is described
[in the historical record](docs/history/provenance.md).
