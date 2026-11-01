# ADR-006: Managed tree labels and persistent occurrence numbering

- Status: Implemented in addon 0.5.0
- Date: 2026-11-01

## Decision and implementation plan

Display each supported managed component link as `ITEM-REVISION|OCCURRENCE`.
Number per exact target Item/Revision within its immediate assembly container
(`Assembly::AssemblyObject` or `App::Part`); ordinary document groups do not create
an engineering scope. Uncontained links use document scope. External subassemblies
are occurrences in their parent, with their own document defining child scopes.
The owning document displays `ITEM-REVISION`; descriptions remain in metadata.

Persist an occurrence UUID, index, allocation key and original description on
each App::Link. A versioned JSON registry on the document's existing hidden
metadata object stores ownership and per-scope high-water marks. Deleted indices
are not reused. Existing occurrences retain numbers; copied links get fresh IDs
and indices. Changing parent/target revision allocates in the new scope while
retaining the occurrence UUID. A new revision of the owning assembly preserves
occurrence lineage; a different owning Item starts a new registry.

Implement a pure allocation planner, a GUI-thread document adapter, integration
with managed upload/retrieval and an additive Refresh Tree Labels command.
A debounced document observer updates newly inserted supported links in managed
working copies after native transactions finish. It uses an unexpired owned
checkout verified by a prior authenticated command, performs no startup network
requests and never edits foreign or retrieved documents in the background.
The explicit refresh/upload paths check the current checkout through the API.
Server authorization and immutable file rules remain authoritative for uploads.

Reconstruction updates only its newly owned local copies before save/hash/readonly
finalization. Original files, cached/server blobs and already-open dependencies
are not rewritten. User working edits remain normal unsaved CAD changes until
saved/uploaded. Internal object Names and Item/Revision UUIDs remain reference
identity; displayed labels are never parsed for PDM identity. BOM positions and
quantities are independent of occurrence indices. No API/database migration.

Validate allocation stability, copy/delete/reparent/revision behavior, unknown
links, conflicting parents, no-op refresh, save/reopen, packaging and imports.
Use actual FreeCAD to verify native links, repeated occurrences, placements,
grounding, observer insertion, historical retrieval and current toolbar behavior.

## Evidence and limits

Implementation and validation are recorded in [the feature report](../freecad-tree-labels.md).
The observer's lease cache governs local CAD presentation edits; backend checkout
and permission checks remain authoritative for uploaded state. Check-in/release
invalidate cached permission. A raw FreeCAD file-open can reset the document
heading to its filename; managed retrieval/refresh projects the heading again
without reallocating stored link indices. Source snapshots with no registry get
local projection IDs until first managed upload persists that migration.
