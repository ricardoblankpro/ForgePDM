# ADR-026 — Versioned item description localization

Status: Accepted. Date: 2026-11-16.

## Context

Item identity and engineering revisions must remain language-independent.
Legacy text spans item designation/master description and revision descriptions;
P revision descriptions are frozen material snapshots. Existing CAD metadata,
description tokens and released files must remain compatible.

## Decision

Migration 19 adds `items.source_language` and three small relational tables:
`localized_text_sources` identifies an item/optional-revision/field context;
`localized_source_versions` retains immutable original text/language versions;
`localized_translation_versions` retains drafts, approvals, supersession,
review invalidation, attribution and provider provenance. Missing is absence.
Unique context indexes and explicit immediate transactions prevent duplicates.

The localization service owns read authorization, editing permissions, resolution,
optimistic tokens, approval, source history and invalidation. Existing item and
description services synchronize source versions in the same write transaction;
reads never initialize or repair metadata. The canonical legacy columns remain
unchanged. They are deliberate compatibility projections, with original text
history retained separately rather than a second independently editable original.

New callers supply a supported source language. Existing text migrates verbatim
as `und`; no language is inferred. Each context can be explicitly relabeled.
Designation language also updates item source-language metadata. Relabeling does
not promote translated text. An original text or language change invalidates
active translations instead of rewriting them. Editing an approved translation
creates a new draft while retaining the old approval until replacement approval.
Approval requires a current saved draft and confirmed original language.

Enabled project/library editors, owners and administrators can draft and approve,
including self-approval and translation after release. This is a presentation
review policy, separate from engineering release. Original edits keep existing
checkout/lifecycle fences. Audit events and source/translation versions retain
provenance. Source-level optimistic tokens reject concurrent changes atomically.
Unchanged revision text carries translation records with explicit copy provenance.

English and pt-BR start the registry. The pure backend proposal function and local
terminology data are optional provider boundaries; neither client imports server
logic. Structured fastener proposals preserve engineering tokens and return draft
text/warnings. A matching pinned material translation can seed an independent P
draft. Unknown terms require review. No external dependency or automatic approval
is introduced. Future providers can return the same text/language/provenance
proposal contract without participating in item identity or approval policy.

Catalog search filters permissions and approved current-source translations before
pagination, with Unicode case/accent normalization. Requested-language catalog
and BOM presentation use the shared resolver and original fallback. BOM selection
keeps exact revision pins, quantities, relationships and mass evidence. Frozen
format-3 drawing data records language/provenance; formats 1/2 and published bytes
remain untouched. A localized report token excludes generation time.

## Alternatives and consequences

Per-language items or engineering revisions would duplicate identity and break
references. Per-language columns require schema changes for each new language.
A mutable JSON dictionary cannot reliably preserve approval history or concurrent
review. A general translation platform/external SDK adds complexity before needed.
The normalized tables offer indexed lookup, explicit history and a straightforward
PostgreSQL path while keeping SQLite and existing transactions.

Source-text duplication is limited to the history required for review and existing
compatibility columns. Retaining this history costs storage but proves which
original was reviewed. Catalog source rows and presentation resolution currently
use adjacent authorized read transactions; a concurrent edit may require refresh.
BOM reports use one consistent read transaction. Unicode search uses a registered
SQLite function and substring scans; larger catalogs should adopt an indexed
search strategy in a separate migration. Supported language choices are shipped
by both clients; adding a language also requires updating those choices.

No UI internationalization, machine language detection, source promotion, bulk
migration classification, external provider, automatic PDF regeneration or
four-eyes review policy is included.
