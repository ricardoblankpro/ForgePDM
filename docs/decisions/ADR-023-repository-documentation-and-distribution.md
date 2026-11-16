# ADR-023 — Current documentation and independent addon artifacts

Status: approved repository cleanup; public distribution remains deferred.

Keep one source monorepo with separate backend/addon packages. Replace mixed
current/history guides with eight task-oriented user guides, operations and
contributor references. The concise development handoff owns delivery identifiers
and recent verification; dated engineering chronology and plans are archived.
Preserve numbered ADRs, migrations, compatibility APIs and original validation
reports. Remove inactive prototype copies only after dependency review; their
unchanged source remains in the recorded Git commit.

Canonical user guides live in `docs/user`. The addon packager copies these and
the server operations guide into its archive, rewriting relative links to their
installed names. Unshipped developer/history references become canonical online
links. No committed duplicate manual, backend package dependency, runtime download
or network startup work is introduced. Packaging must reject invalid resources
and prove every local installed-document target exists.

Consolidate native acceptance harnesses under addon development tooling and derive
repository paths from the harness location. Keep unit/Qt and native evidence
separate. Documentation/link/version/portability checks join CI; artifact creation
remains reviewable and does not publish a release or distribution branch.

The owner approved LGPL-2.1-or-later for the Workbench and AGPL-3.0-or-later for
the server, with ricardoblankpro@gmail.com as public maintainer contact. Record
license scope in LICENSING.md and include full GNU texts. Third-party schema
terms remain separate. Release-check verifies metadata/source prerequisites;
local packaging success does not imply Addon Index approval.

Large command/route refactors are separate increments. Changes here preserve
command IDs, authoritative PDM rules, saved engineering formats, file pins and
backend/schema compatibility.
