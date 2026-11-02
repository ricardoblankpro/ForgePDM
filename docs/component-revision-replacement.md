# Explicit component revision replacement

Implementation scope approved by the user: add a FreeCAD command to explicitly
adopt a newer revision while maintaining precise assembly references.

## Plan

1. Select direct occurrences of one managed component revision in a clean local
   Working assembly with an owned checkout. Use the existing bounded BOM adapter
   to distinguish direct components from generated subassembly children.
2. Select a newer revision and an exact uploaded native snapshot. Retrieve it
   through the existing verified configuration/cache path, without repurposing any
   already-open source document or fetching implicit latest data.
3. Review the occurrence list and revision/snapshot. Recheck source document,
   checkout and references after asynchronous work and dialogs.
4. Update link targets in place inside an undoable FreeCAD transaction. Preserve
   names, placements and occurrence UUIDs. Check joint references and object error
   states; abort rather than retain a broken replacement. Do not run the solver or
   infer semantic equivalence of changed faces from equal names.
5. Leave the assembly locally modified for inspection. Save/upload and reviewed
   BOM synchronization remain explicit separate operations. Released parents
   require their own new assembly revision. No backend/schema change.

Validation covers selection/cancel, lifecycle/checkout guards, same-item newer
revision verification, target mapping, repeated occurrences, placements, constraint
preservation/rollback and packaging. Live tests use an isolated backend first;
user documents and previously open revisions must be preserved.

## Implemented behavior — addon 0.5.7

`ForgePDM_ReplaceRevision` is registered in the normal menu/toolbar. A component
selection defaults the occurrence checklist to the selected direct links; all
other matching occurrences remain available for explicit selection. The user
chooses among newer non-obsolete revisions and their exact uploaded snapshots.
Working target revisions are identified in the dialog and can be chosen explicitly.

A separate downloaded configuration supplies verified replacement objects.
Cancel/failure closes only clean documents opened by this operation. Parent
permissions, owned checkout and clean/source state are checked again after review.
Replacement runs as one local transaction, including tree occurrence projection.
All direct component placements and unselected targets are checked after recompute.
Joint links/subelement paths must remain resolvable and unchanged; external source
joint references and unsupported mappings fail conservatively. Recompute is used
for validity; the command does not explicitly run the assembly solver.

Compatible object names/types are required across revisions. A face retaining its
name may still have changed engineering meaning; final geometry/joint inspection
is required. Generated subassembly children can be recreated with different local
names, so a joint to such a child may block replacement rather than be guessed.
No new backend mutation endpoint, database migration or implicit BOM write exists.

Validation: 201 automated addon tests; isolated live command workflows verify
cancellation, selected-only replacement, retained occurrence UUIDs/placements,
unchanged grounded constraints, untouched stored BOM/files until explicit upload,
verified new upload pins and real rollback after an injected failure. Disposable
native AssemblyLink tests verify both unconstrained replacement and rejection/
rollback of an unsafe generated-child joint mapping. The actual registered command
was opened on A000001 and canceled; its checklist selected P000006-A|1 and left
P000006-A|2 unchecked, and the user's assembly remained unchanged.
