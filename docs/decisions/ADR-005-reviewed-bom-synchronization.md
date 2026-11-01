# ADR-005: Explicit engineering occurrences and reviewed BOM replacement

- Status: Implemented for the bounded App::Link profile
- Date: 2026-11-01

## Decision

Keep the immutable CAD reference graph separate from the engineering BOM. A
GUI-thread adapter captures whole-object links in one assembly document and
resolves internal repeated links to external pinned targets. Plain groups/parts
are organizational; external subassemblies are direct engineering components.
Users explicitly select occurrences; each contributes one unit, grouped by exact
revision. The review displays provenance, quantities, revisions, all existing
manual lines and the complete replacement. No inference from labels, filenames,
visibility or latest-revision lookup is permitted.

Support a review-and-replace workflow instead of silently merging or deleting
manual engineering lines. A positive replacement consent is required, including
when clearing an assembly. Existing BOM revision-copy and lifecycle rules remain.
The adapter rejects unsupported/ambiguous structures rather than guessing units.
Provenance is transient review data; persistent CAD-to-BOM traceability and
third-party adapter contracts can extend this bounded implementation later.

## Concurrency boundary

Expose additive snapshot/synchronize API routes. A snapshot reads authorized
direct BOM lines, a hash of their stored identities/values and the active owned
checkout ID in one transaction. Synchronization checks those preconditions under
SQLite's existing `BEGIN IMMEDIATE` transaction before applying established BOM
policies and replacement. Including stored line IDs detects intervening replacements
even when quantities return to prior values. Reacquired leases have different IDs;
renewing the same lease preserves its identity. Responses read the resulting BOM
inside that transaction. No schema migration or new dependency is needed.

This fences this synchronization operation against BOM edits and lease turnover;
it is not general fencing of legacy writes, nor an idempotency protocol. An
uncertain HTTP result must be inspected before another proposal; no mutation retry
is automatic. Atomic CAD upload/manifest/check-in remains Phase 5. The backend
remains authoritative for permissions, lifecycle and engineering BOM validity.
Client CAD checks do not turn an untrusted extraction claim into a server guarantee.

## Change to retrieval semantics

ADR-004's rejection of a nonempty engineering BOM with a different child revision
set is superseded. Engineering selection can intentionally exclude CAD dependencies
and manual lines can reference components outside the native dependency graph.
Retrieval records the difference and reconstructs exclusively from exact CAD
manifest pins, retaining every hash, permission and object identity check. Set
equality reports only revision-set agreement, not engineering quantity correctness.

## Architectural references and tradeoffs

Teamcenter's Item/Revision/Dataset/BOM separation remains the conceptual model.
Legacy FreeCAD link macros inform occurrence-oriented interaction, but their
label parsing and implicit overwrite behavior are not adopted. EasyPDM remains
a workflow reference; no third-party source is copied. The bounded adapter and
explicit replacement keep the MVP small, at the cost of manual component selection,
no automatic BOM refresh on upload and no certified third-party assembly support.

## Native Assembly extension (addon 0.4.2)

A single `Assembly::AssemblyObject` containing direct supported App::Link
components is now recognized. Standard JointGroup/Joint/GroundedJoint objects
are constraints and do not add engineering occurrences. Nested local native
assemblies, custom proxies and other unsupported structures remain rejected.
The extension does not change manifest, selection, review, quantity, lifecycle
or concurrency rules. See [scope and evidence](../freecad-builtin-assembly.md).
