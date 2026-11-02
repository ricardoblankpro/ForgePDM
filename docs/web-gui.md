# Read-only web GUI — first increment

Approved scope: bring basic web browsing forward from Phase 8 while Phase 5
backend reliability remains the next backend priority.

## Implementation plan

- Serve a buildless HTML/CSS/JavaScript client at `/app/` from FastAPI. Keep all
  business rules and authorization in the versioned API. No hosted copy, external
  tunnel, third-party runtime/CDN dependency or deployment change is required.
- Reuse password/bearer authentication. Keep tokens in page memory only; refresh
  requires sign-in. Clear browser state on logout or expired sessions. Never put
  tokens in URLs, persistent browser storage or downloads' query strings.
- Browse authorized projects and paginated/searchable items, choose exact
  historical revisions, inspect datasets/download files, explore immediate and
  multilevel revision-pinned BOMs, and navigate where-used relationships.
- Add an optional authorized `project_id` catalog filter, preserving existing
  default behavior and preventing disclosure through inaccessible projects.
- No item/BOM/lifecycle/checkout editing, automatic component updates, CAD preview,
  flattened BOM view, ERP integration or new database schema in this increment.
- Validate permissions and packaged assets with backend tests, pure client logic
  with Node tests and the real UI with isolated browser/API fixtures when available.

The client is a separate presentation module under `src/forgepdm/web`; FastAPI
only serves those assets. This keeps installation simple for the local prototype
and permits a future independently hosted client using the same API. Same-origin
hosting avoids opening cross-origin access to the backend. Hosting/publication
remains local because the current server and data live on the user's computer.

## Current behavior

Open `http://127.0.0.1:8000/app/` with the normal local backend running. Sign in
using the existing ForgePDM account; browser and FreeCAD sessions are independent.
The shell is public, but every engineering-data request uses the normal API
bearer authentication and server permission checks. No demo records or credentials
are embedded in the production client. All labels/descriptions are rendered as
text, with a same-origin Content Security Policy and no external assets/scripts.

The optional `GET /api/v1/items?project_id=UUID` filter applies project membership
and active-project checks before pagination. An item shared into an inaccessible
project does not reveal that relationship through the filter. Omitting the filter
preserves the FreeCAD catalog contract.

Revision selection and BOM/where-used navigation retain exact IDs. The current
revision is available as an explicit choice; historical views are never silently
substituted. Multilevel rows can be expanded/collapsed. Quantities are those within
the immediate parent, with no implicit rollup or flattened parts aggregation.
Empty stored subassembly BOMs have no expanded children; synchronize those BOMs
from their respective FreeCAD working documents first.

Dataset downloads use authenticated fetches and individual file bytes. They do
not reconstruct an assembly's entire linked configuration. Use FreeCAD's download
workflow for that. Very large browser downloads currently materialize a Blob;
streaming/download-ticket support remains future operational work.

Tokens stay in page memory, not local/session storage, cookies or URLs. Logout
revokes the browser token and clears loaded data; expiration clears the UI and
asks for sign-in. A page refresh requires sign-in again; the server-side token
previously issued still follows its existing expiry policy. No automatic token
refresh, SSO, browser CAD rendering or web editing is included.

## Validation

- 57 backend tests pass, including static routing/headers, project authorization,
  cross-project membership non-disclosure, pagination and invalid UUID rejection.
- Three Node model tests pass: historical navigation, repeated subassembly path
  identity/exact quantity preservation, and file-size display.
- 26 real Chrome checks pass against a disposable FastAPI/SQLite/file-store
  fixture. These cover login/errors/logout/expiry, project filtering/pagination,
  exact historical BOM navigation, direct/multilevel controls, where-used links,
  revision-specific datasets, authenticated download bytes, XSS-safe text,
  memory-only tokens, CSP and mobile layout. No engineering writes or uncaught
  browser exceptions occurred.
- Desktop login/catalog/BOM and mobile BOM screenshots were visually inspected.
- The Python wheel includes all six static web assets. No frontend dependency
  installation/build is required for a normal ForgePDM deployment.
- Targeted backend/new-test lint and formatting checks pass. Broad repository lint
  includes unrelated existing findings; no repository-wide cleanup was attempted.

Evidence: [browser report](validation/web-gui-browser-2026-11-02.json).

Reproduce the automated checks from the repository root:

```sh
uv run --group dev pytest tests -q
node --test tests/web/model.test.mjs
uv run python tests/web/serve.py --case /tmp/forgepdm-web-qa-case
```

The last command stays running and generates private fixture credentials under
that temporary directory. In another terminal, with a Chromium/Chrome executable:

```sh
npm install --ignore-scripts --no-audit --no-fund --prefix /tmp/forgepdm-web-qa playwright-core
node tests/web/browser.mjs /tmp/forgepdm-web-qa-case
```

`FORGEPDM_PLAYWRIGHT` can point to another playwright-core `index.mjs`, and
`FORGEPDM_BROWSER` to another Chrome executable. The harness defaults to
`/usr/bin/google-chrome`, uses only disposable data, writes screenshots/reports
under the fixture directory and does not print credentials.
