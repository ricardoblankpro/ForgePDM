# ADR-012: One Item Master and revision-bound manufacturing inputs

Status: implemented as migration 13, 2026-11-07; normal user workflow superseded
by [ADR-013](ADR-013-simple-material-and-assembly-descriptions.md). Retained as
the historical advanced-input/API design. In the current workflow, an M requires
only its description for release; the mandatory specifications below describe
the earlier increment, not the current release rule. Physical links/mass and S
reference mass are specified by ADR-014 and ADR-015.

Reuse Items, numbering counters, revisions, lifecycle and project authorization.
Add M as a part-kind numbering series and extend the existing shared S library.
Do not allocate parallel ERP/purchasing identities or move engineering items.

Keep the existing assembly EBOM contract. Store P/A manufacturing-input headers
with canonical payloads for concurrency hashing, plus indexed relational input
lines with exact component revision foreign keys, units and decimal quantities.
Flexible technical specifications use bounded validated JSON, consistent with
existing Standard Parts; identity and base UOM have dedicated columns. This
avoids fixed columns for every possible stock profile while preserving explicit
quantity/unit columns and searchable material relationships.

Use existing engineering revision approval. Material completeness is explicit
and separate from engineering release, preserving existing P/A rules. New M
releases require specifications. No independent MBOM revision/lifecycle exists.

An M identity is grade + standard + stock form + defining section dimensions +
base UOM. Normalize text and decimal dimensions. Identity changes allocate a new
code; density/description/conversion changes use revisions. Purchase sizes are
metadata, with cutting optimization deferred.

Publish native material evidence with its dataset using the existing metadata
transaction and file-hash replay. Reset completeness when engineering evidence
changes. Web/CAD conflicts cannot silently substitute latest material revisions.

Calculate gross demand from explicit exact-revision roots in a consistent read.
Preserve paths and per-revision subtotals; fail on inaccessible branches. Freeze
approved source data in immutable snapshots rather than relying on mutable
Working definitions. Integration exports carry schema/calculation versions and
content fingerprints. Future ERPNext delivery is a separate adapter with durable
idempotent external document mappings, not part of domain or FreeCAD logic.

This is a bounded engineering material BOM, not a manufacturing routing system.
ERPNext retains operational/inventory ownership. Teamcenter is a conceptual
identity/revision reference; no claim of equivalent enterprise MBOM or effectivity
semantics is made. No third-party source was copied.
