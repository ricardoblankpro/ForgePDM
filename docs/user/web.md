# Web workspace

Open `http://127.0.0.1:8000/app/` with the backend running, or use your configured
server address. The backend serves the web client directly; no separate frontend
server or JavaScript build is needed. Sign in with a ForgePDM account. Browser
and FreeCAD sessions are independent. Tokens stay in page memory, so refresh
requires sign-in again.

## Engineering navigation

Browse authorized projects/items, filter/search the catalog, select an exact
revision and inspect its description, BOM, drawings, datasets and where-used
relationships. Links retain recorded revision IDs. Newer revisions are displayed
separately; historical selections are never silently replaced.

The BOM tab offers the same [Direct/Indented/Flattened reports](bom.md) as
FreeCAD, including quantities per parent/root, masses and missing evidence.
Refresh BOM fetches new values. The [Drawings tab](drawings.md) previews or
downloads source-pinned PDFs. Dataset downloads fetch individual files; use
FreeCAD to reconstruct a complete managed assembly configuration.

The Description tab edits checked-out P/A/M descriptions and material assignment.
S entries show mass source and optional lookup/manual controls. Administrators
can import exact supplier-reference CSV. See [materials and mass](materials.md).
General CAD replacement and engineering BOM editing remain FreeCAD workflows.

## Accounts and projects

Administrators manage users, temporary password resets, enabled state, project
properties and project memberships. Project properties include customer, due
date and description. New/reset accounts must change their temporary password
before accessing engineering data. Password reset revokes existing sessions.

Project roles are viewer, editor and owner. Viewers read; editors/owners can
perform permitted edits under checkout. Global administrators can access all
items. Ordinary projectless P/A items are admin-only; shared S/M library readers
and curators have their own scoped access. Removing membership changes subsequent
access without deleting the underlying item history.

All users can change their password, inspect My Checkouts and browse authorized
activity. Expired leases are labeled; administrative overrides require reasons.
Archived projects retain data/history. The server prevents disabling the active
administrator through the normal self-management flow.

Descriptions are rendered as text. Engineering requests and downloads use normal
API authorization; no credentials are embedded in datasets' public links.
Production deployment requirements are described in [operations](../operations/server.md).
