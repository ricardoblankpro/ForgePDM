# ADR-033: Managed editing sessions and recoverable cancellation

Status: accepted for addon 0.28.0, backend 0.3.4, schema 21.

## Context and decision

Checkout previously moved a live document through Save As, affecting incoming
links while discarding the working record's baseline. Representation v1 required
all live member links to resolve before update, making a deleted fastener prevent
its own reconciliation. These are client coordination problems; immutable server
snapshots and exact revision/file pins remain authoritative.

Fork clean retrieved documents into separate working documents with retained
source provenance. Component updates compare the saved local parent state rather
than requiring another parent upload. Keep historical opening exact; Open for
Editing offers updates within existing revisions. Different revisions remain an
explicit engineering choice, extending rather than replacing ADR-007.

Freeze saved local dependency graphs into immutable local configurations. Their
identities cannot be submitted as server dataset IDs. Representation v2 retains
source and member identity independently of live links, and reads v1 without
rewriting it. Owned source saves assign persistent member UUIDs. Reviewed
reconciliation requires verified saved source identity and preserves surviving
member names, occurrence IDs, placements and resolved joints. Unknown or
ambiguous identity fails closed. This extends ADR-032.

Graph publication freezes inputs before any upload and publishes children before
parents. Reuse atomic native publication with a new explicit save endpoint that
retains checkout. Its intent fingerprint distinguishes save from check-in.
Per-document journals and a graph journal recover original results without
releasing later leases or substituting newer edits. This is not distributed
atomicity; completed child operations remain durable after a parent failure.

Cancel Check Out retains recovery copies, restores affected open parent
occurrences and releases only the reviewed lease. Schema 21 stores actor-scoped
cancellation intents/results atomically with checkout release. Replay returns the
original result. Reviewed snapshot pins and checkout UUID/version are preconditions.
Local restoration and server release have separate durable journal states;
interrupted results must be recovered. Uploaded history is never deleted.

## Boundaries

Server-owned lifecycle, permission, revision and exact manifest rules remain.
No backend imports occur inside FreeCAD; GUI operations and HTTP workers remain
separate. BOM synchronization remains an independent reviewed engineering action.
Distinct configurations of the same revision require explicit resolution before
graph publication. Flexible subassemblies and reverting published history remain
outside this increment. Recovery bundles and frozen graph inputs have no automatic
pruning. Legacy records cannot infer an unknown baseline from the latest upload.
