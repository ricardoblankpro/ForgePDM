# Functional web workspace — implementation plan

User-approved priorities: user administration, password management, project
properties and access, my checkouts, and searchable activity history.

1. Add migration 8: project customer/due date/description and a user password-change
   requirement. Preserve existing data and default existing accounts to unchanged.
2. Add a separate management application/API module. Recheck current admin status
   inside write transactions; preserve the last enabled admin and prevent unsafe
   self-demotion/disable. Usernames remain case-insensitively unique.
3. Admins create/enable/disable/change roles and reset passwords. Users change their
   own password with the current password. Reset/change/disable/role changes revoke
   sessions; reset/new temporary passwords require change before other API access.
   Keep the established four-character password minimum, including numeric values.
4. Admins create/edit/archive projects and maintain owner/editor/viewer membership.
   Keep existing owner semantics; new project administration is global-admin-only.
   Regular users may read their projects, including properties. Archiving retains
   membership/items/history and excludes the project from active catalog selectors.
5. My checkouts shows the actor's active and expired unreleased leases, filtered
   by current item access, with exact revision links. No new checkout mutation UI.
6. Activity queries paginate/filter by action, actor, project, dates and search.
   Admins see all events; regular users see accessible engineering/project events
   and their own account events. Hide raw details from non-admins to avoid exposing
   related inaccessible component identities. Do not log passwords/tokens.
7. Extend the existing same-origin buildless client with Users, Project management,
   Account/password, My checkouts and Activity pages. Keep tokens only in memory;
   forced-password sessions get only the password screen and sign-out. Handle
   rejected/stale requests inline and disable submit buttons while saving.
8. Validate domain/API authorization, migration, password/session behavior, old
   FreeCAD contracts, and real browser workflows against disposable fixtures.

This brings a bounded portion of Phase 8 forward. CAD/revision/BOM mutations and
Phase 5 follow-ups remain separate. No email/reset-link service or automatic
password distribution is introduced; admins securely provide temporary passwords.

## Implemented behavior

The local workspace at `/app/` now provides:

- **Users** (administrators): paginated accounts, create with temporary password,
  edit display name/role/enabled state, reset another user's password. Failed
  self-disable/demotion and last-admin changes show an inline error. No account
  deletion or automatic password distribution is provided.
- **My account**: current/new/confirmation password form. Password changes revoke
  all sessions, including the current browser and FreeCAD sessions. New/reset
  users must change their temporary password before any engineering or management
  API access. The backend enforces this, including for older CAD clients; use the
  web password form before signing in again in FreeCAD. Existing accounts retain
  their current passwords and do not receive a new change requirement.
- **Project management**: project number, name, customer, due date, description,
  archived state. Admins maintain membership and owner/editor/viewer roles;
  regular members see read-only properties. Archived projects remain inspectable
  here, but disappear from active catalog selectors. Archiving does not delete
  data or change the established engineering permission rules.
- **My checkouts**: paginated active/expired unreleased leases for accessible items,
  acquisition/expiry time and exact revision navigation. Refresh updates the list.
- **Activity history**: project, visible-user, exact-action, text and inclusive
  UTC-date filters. Stable pagination; exact item/revision links. The user picker
  includes actors of visible events, rather than exposing the account directory.
  Admins may expand structured event details; non-admins see no raw detail payload.

Tokens remain in memory. Password fields are cleared after submission and dialogs
are removed on close/logout. Sessions are revoked on password reset/change,
account disable and role change. Auth/account responses add only the password-change
flag; no password hash or session token is exposed by administration queries.

### API additions

- `GET/POST /api/v1/admin/users`
- `PUT /api/v1/admin/users/{user_id}`
- `POST /api/v1/admin/users/{user_id}/reset-password`
- `POST /api/v1/auth/password`
- `GET/POST /api/v1/management/projects`
- `PUT /api/v1/management/projects/{project_id}`
- `GET /api/v1/management/projects/{project_id}/members`
- `PUT/DELETE /api/v1/management/projects/{project_id}/members/{user_id}`
- `GET /api/v1/me/checkouts`
- `GET /api/v1/activity`, `GET /api/v1/activity/actors`

Additive migration 8 preserves existing users, projects, datasets, sessions and
checkouts. A consistent private metadata backup was taken before local migration.
The standalone web assets remain packaged with the Python wheel, including the
new `management.mjs` module. No addon update or frontend build is required.

### Validation

- 98 backend tests, including account/reset/session enforcement, last-admin and
  stale-admin checks, member/archived-project access, scoped checkouts/events/user
  picker, date/input validation, pagination and migration 7-to-8 preservation.
- 228 addon tests and 3 Node web model tests pass.
- 26 existing Chrome browsing checks and 23 management Chrome checks pass against
  disposable SQLite/storage fixtures, with no uncaught browser errors. The latter
  exercise real UI writes, mandatory password changes, XSS-safe customer text,
  project membership, exact checkout links and revocation of another live browser.
- Desktop/mobile screens visually inspected. Mobile tables preserve readable
  widths and scroll internally; page width remains within the viewport.
- Focused lint, JavaScript syntax, whitespace checks and wheel packaging pass.

Evidence: [management browser report](validation/web-management-browser-2026-11-02.json).
Reproduce using `tests/web/serve.py --case NEW_PRIVATE_TEMP_DIR` followed by
`node tests/web/management-browser.mjs NEW_PRIVATE_TEMP_DIR`. Each management run
needs a fresh fixture because it creates uniquely named users/projects. The same
Playwright/Chrome configuration as the original browser harness applies.

## Suggested independent test sequence

1. Sign in as an existing administrator at `http://127.0.0.1:8000/app/`.
2. Create a test user with a temporary password and a test project with customer,
   due date and description. Add the user as viewer.
3. In a separate browser profile/private window, sign in as that user. Change the
   temporary password, sign in again, and verify only assigned projects appear.
4. Change their project role to editor and test allowed/denied FreeCAD actions.
   Check that revision pins and assembly structure remain unchanged.
5. Check out a test revision in FreeCAD; inspect My checkouts in the web GUI and
   follow its exact revision link. Check in, refresh and confirm it disappears.
6. Inspect activity by project, user, action and date using both accounts. Compare
   admin details with the restricted non-admin view.
7. Reset the test user's password while their browser/FreeCAD session is active.
   The next request must require sign-in; the temporary password must require change.
8. Disable/re-enable the test account and verify sign-in behavior. Try disabling
   your own administrator account and confirm the operation is rejected.
9. Remove project membership and verify the user's subsequent requests lose access.
   Archive/unarchive the test project and verify properties and history persist.

The remaining Phase 5 reliability work, flattened BOM tools, revision comparison,
profile preferences, email recovery and web engineering mutations are deferred.
