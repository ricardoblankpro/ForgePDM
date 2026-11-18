# ADR-027 — One description per revision

Status: accepted, 2026-11-18. Supersedes the separate ordinary text contexts of
ADR-026 and extends ADR-013 with manual unassigned P and generic S descriptions.

The ordinary UI exposes one revision description and one translation workflow.
P with material retains an exact M revision/text/physical snapshot; unassigned P
accepts manual component text. Explicit clearing removes assignment and text.
A has one manual assembly description. Structured S descriptions are fixed by
specification; generic S remains manual. M has one revisioned material description.
Identity remains the permanent number/UUID. Specifications and BOM pins do not change.

Schema 20 consolidates legacy text into revision_descriptions, preferring existing
revision text, master text, then item name. Assigned material snapshots are never
replaced by item text. description_consolidation records the prior row and whether
backfill used revision or legacy shared item text. Historical item names/master
text and their original localization records remain available; backfill is not
proof of historical revision-specific authorship.

Matching confirmed source text/language permits attributed copies of translations.
Conflicting approvals copied from legacy contexts require review. Existing original
contexts and histories are retained. Old localization editors can mirror writes
only when source text matches the current canonical revision and no independent
translation changes exist; otherwise they receive a reconciliation conflict.

Description endpoints retain their payloads and concurrency tokens. Read responses
add origin; standard capabilities advertise description_model_version=2. Native
metadata formats 1/2 remain readable. Old working copies with changed tokens must
reconcile; migration does not save CAD, update frozen drawings, regenerate PDFs,
change exact pins or adopt newer M snapshots. Historical compatibility columns
remain; ordinary clients do not offer three independently editable descriptions.

A schema-19 backup and isolated migration rehearsal precede local deployment.
Native/platform acceptance must be reported separately from fake/Qt tests.
