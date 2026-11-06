# ADR-011 — Shared Standard Parts Library

Status: accepted, 2026-11-05. Extends ADR-010.

S items represent reusable purchasing identities. Assigning one to its first
consuming engineering project fragments the catalog and ties reuse to unrelated
project permissions. Use one dedicated shared library, represented by an ordinary
Project with a unique immutable API-level `is_standard_library` flag. This reuses
existing membership, checkout and lifecycle rules without adding a second catalog
permission model or changing Item/Revision/BOM separation.

Every S creation resolves to the library on the backend, including requests from
older clients that supply a different project ID. Native S uploads and generic or
Fasteners registration omit the project prompt. P/A items cannot be created in the
library, which is excluded from editable engineering-project pickers and cannot be
archived. Administrators manage its membership through existing project management.
Enabled accounts start as viewers. Editors/owners and global administrators can
maintain standard items. Referencing an S revision in an assembly grants no edit
rights and adds no consuming-project membership to the S item.

Migration 12 creates the library without hijacking an existing similarly numbered
project, enrolls enabled users, grants existing S creators editor membership, and
moves all S project memberships to the library. Preserve UUIDs, numbers, names,
revision history, files, BOM pins, checkouts and audit history. Existing equivalent
specifications are not merged: that would require an explicit identity-replacement
workflow. Unique legacy specification scopes become the library; duplicate legacy
scopes remain intact. New registration checks the full shared library for exact
specification duplicates within its write transaction.

New enabled accounts created through management or CLI receive viewer membership;
re-enabling an account also restores default reader membership. Unrelated account
edits do not undo explicit access revocation. Direct database account insertion is
an administrative bypass and must enroll users explicitly.

This retains ForgePDM's Teamcenter-inspired domain separation and uses its existing
project ACLs as the MVP library container. It does not introduce enterprise library
hierarchies, suppliers, automatic substitutions, auto-release or catalog merging.
The library still appears as a project in management and browsing; a separate
library UI can be added without changing engineering identity.
