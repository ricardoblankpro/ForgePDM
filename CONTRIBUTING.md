# Contributing to ForgePDM

Read the [current handoff](DEVELOPMENT_STATUS.md), [architecture](docs/development/architecture.md)
and applicable `AGENTS.md` before changes. Use the [documentation index](docs/README.md)
for current behavior; dated phase reports are historical records.

## Set up

Use Python 3.11+, uv and Node.js for the pure web tests:

```sh
uv sync --group dev --locked
uv sync --project clients/freecad --extra dev --locked
```

The backend and addon have independent Python environments/lockfiles. Do not
install backend dependencies or another Qt binding inside FreeCAD. Start a local
server using [operations](docs/operations/server.md); use disposable data for
mutation tests. Keep engineering data, credentials and generated archives out of Git.

## Boundaries and compatibility

Backend application services own authorization, transactions, revision/lifecycle
and storage rules. FreeCAD is an HTTP client; its runtime cannot import backend
business logic or access the database/blob store. Keep CAD/widget operations on
the GUI thread and HTTP/transfer work on workers. Preserve command IDs, native
metadata, exact revision/dataset/file pins and durable operation recovery.

An old API, workspace record, migration or test is not automatically obsolete.
Document compatibility changes and prove existing data can still be read/upgraded.
The duplicated standard-part contract is deliberate: a parity test keeps the
independent client and server copies identical. Keep schema provenance and
supplier/fastener research sources when reorganizing files.

## Verify

Run the same tiers used by CI, from the repository root:

```sh
uv run --group dev --locked ruff check src tools tests/test_repository_docs.py
uv run --group dev --locked ruff format --check src tools tests/test_repository_docs.py
uv run --group dev --locked pytest tests -q
node --test tests/web/*.test.mjs
uv run --project clients/freecad --extra dev --locked pytest clients/freecad/tests -q
uv run --project clients/freecad --extra dev --locked ruff check clients/freecad
uv run --project clients/freecad --extra dev --locked ruff format --check clients/freecad
uv run --project clients/freecad --extra dev --locked python clients/freecad/tools/addon.py check
uv run --project clients/freecad --extra dev --locked python clients/freecad/tools/addon.py build
uv run --group dev --locked python tools/check_docs.py
```

The explicit backend/tooling lint baseline is E4/E7/E9/F/I; the addon retains
its E4/E7/E9/F baseline. Stronger lint policy changes are reviewed separately.

See [test tiers](docs/development/testing.md) for optional real Qt, browser and
native acceptance. Base pytest skips Qt modules when PySide6 is absent; report
that separately from native FreeCAD evidence. Do not run GUI harnesses against
another person's engineering data. New domain rules need automated tests.

## Documentation and review

Keep README an overview/quick start. Maintain current user behavior in `docs/user`,
operations in `docs/operations`, and contributor references in `docs/development`.
Use one authoritative guide per rule and link to it. Do not append a new behavior
below contradictory old instructions. The current handoff owns delivery versions
and recent validation counts; historical guides retain their recorded versions.

Use numbered ADRs for important decisions; record supersession rather than
rewriting their rationale. Move completed plans and chronological engineering logs
to `docs/history`. Keep dated evidence under `docs/validation` with its original
scope. Source user guides are included in the addon package automatically; do not
maintain another manual inside the client directory.

Describe the concrete change, compatibility boundaries and relevant verification
in a PR. Reproduce issues with addon/backend/schema and FreeCAD/Python/Qt/OS
versions, the failing command, error and a minimal disposable file when possible.
Remove credentials and private engineering content before sharing reproductions.
Use the repository's [issue tracker](https://github.com/ricardoblankpro/ForgePDM/issues).

The server uses AGPL-3.0-or-later; the Workbench uses LGPL-2.1-or-later. See
[licensing boundaries](LICENSING.md) and discuss third-party code/assets before copying them. Public release requirements live in
[the release guide](docs/development/releasing.md).
