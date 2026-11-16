# Release preparation

The current addon ZIP is a manual-install preview. Packaging checks and pilot
acceptance do not imply public Addon Index approval. See the [current handoff](../../DEVELOPMENT_STATUS.md)
for tested runtimes and remaining operational limits.

## Build a reviewable artifact

```sh
uv run --project clients/freecad --extra dev --locked python clients/freecad/tools/addon.py check
uv run --project clients/freecad --extra dev --locked python clients/freecad/tools/addon.py build
uv build
```

The addon command prints its exact versioned ZIP path and includes only client
code/resources, metadata and generated current documentation. Backend code,
prototype references, tests, development tools, caches and runtime data are
excluded. User guides have one source under `docs/user`; packaging maps them
under `Documentation/user` and fixes local links. Unshipped developer references
link to the source repository. Inspect extracted contents and test installation
in a fresh profile; retain deterministic hashes with release evidence.

The manual artifact workflow runs checks and uploads versioned build artifacts
and checksums to the workflow run. It does not publish a GitHub Release, modify
a distribution branch or submit an Addon Index entry. Backend package, addon
and schema versions are independent identifiers; update only those that change.

## Licensing, contact and distribution

The owner selected LGPL-2.1-or-later for the Workbench and AGPL-3.0-or-later for
the server, and approved `ricardoblankpro@gmail.com` as the public maintainer
contact. Full GNU texts are included in the corresponding LICENSE files. See
[licensing boundaries](../../LICENSING.md) for shared documentation and the
vendored schema's separate terms. Manifest/Python license identifiers must agree.

A stable Addon Manager distribution source still needs preparation/approval.
`package.xml` is nested in the monorepo, so its root is not an installable addon
source. An addon-only branch can be generated from the reviewed ZIP without
maintaining another source tree; publishing that branch/catalog entry is separate.

`addon.py release-check` verifies machine-checkable license/contact/source
prerequisites and rejects the current monorepo/master locator even after ZIP
extraction. Update the locator only for an approved addon-only source. A passing
result is not a claim of remote-source verification, catalog approval or platform coverage.

## Acceptance before public indexing

Run the documented backend/addon/web/Qt checks, isolated native workflows,
clean startup with the server stopped, and accepted supported-platform tests.
Verify upgrade/rollback data preservation, exact historical retrieval, compatible
backend APIs, offline drawing resources and journal recovery. Document external
server/supplier connections and tested limitations. Do not advertise untested
platforms or prototype production readiness as established support.

FreeCAD's [publishing guide](https://freecad.github.io/Addon-Academy/Guides/Publishing/Indexed)
and [quality requirements](https://freecad.github.io/Addon-Academy/Topics/Addon-Index/Index/Qualities.html)
are the current upstream reference. The [manifest guide](https://freecad.github.io/Addon-Academy/Topics/Structuring/Manifest/)
requires accurate repository branch, maintainer and license metadata. Keep the
pinned [schema provenance](../../clients/freecad/tools/vendor/README.md) used by
our development checks; do not replace it merely because it is vendored.
