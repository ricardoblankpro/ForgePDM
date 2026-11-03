# Update from Server — first increment

`ForgePDM_UpdateFromServer` checks the active managed document for newer native
CAD uploads on its exact revision. It is available in the ForgePDM menu/toolbar.

## Approved implementation plan

1. Compare the managed ledger's exact dataset/file IDs with the most recent
   native snapshot of the same revision, ordered by creation timestamp and IDs.
2. Require a clean document and matching local saved hash. Reject unresolved
   check-in journals, foreign workspaces and inconsistent item/revision identity.
3. Show the chosen timestamp/hash and ask before retrieval. New revision labels
   are informational; do not change revision or dependency pins automatically.
4. Download through the existing verified configuration workflow on a worker.
   Recheck document identity, path, clean state, saved hash and journal after
   retrieval, before opening any new CAD documents.
5. Open and activate a separate verified configuration. Keep the original open
   and preserve its file, checkout and all incoming links. Finish the retrieved
   ledger using the existing read-only snapshot rules. On failure, clean up only
   documents owned by this operation that remain unmodified.

## Usage and boundaries

Select the part or assembly and choose **Update from Server…**. If a newer upload
exists, choose **Open updated copy**. The newly opened document is active; the old
one stays open. Close the old copy when it is no longer needed. Acquire a checkout
on the updated document before editing; the existing checkout workflow creates a
separate managed working copy.

The command reads uploaded snapshots, including uploads before lease release; it
does not wait for check-in. It uses the exact snapshot reviewed even if another
upload arrives during retrieval. Run again to detect later uploads. Current API
snapshot records provide timestamps and hashes but no uploader display name.

For an assembly root, retrieval preserves the uploaded assembly's exact dependency
manifest. It does not independently upgrade every component to its newest snapshot.
For a part linked into an open assembly, the updated copy does not retarget that
assembly. Newer revision adoption remains **Replace with New Revision…**.

Saved but unuploaded changes must be uploaded/checked in or preserved separately
before refreshing. Resolve pending Check In recovery first. This command does not
merge geometry, mutate server data, acquire/release a checkout, modify stored BOMs
or overwrite the original working file. No schema/API/business-rule changes.

## Selected component updates — addon 0.6.3

**Update Selected Components from Server…** handles one source item/revision
group at a time, with an occurrence checklist. Require a clean uploaded managed
Working parent, owned checkout and no pending check-in. Bind original exact pins,
choose the newest same-revision native snapshot, skip already-current occurrences,
and retrieve it through the existing verified configuration path. Review old/new
snapshot IDs, timestamp/hash and affected occurrences before mutation.

Recheck parent bytes/identity, checkout, component references and original exact
pins after asynchronous requests/review. Use the replacement transaction with an
explicit same-revision snapshot mode. Reject identical pins, changed item/revision,
missing/type-incompatible objects and unsafe joints/dependent links. Preserve
occurrence UUIDs, labels, placements and unselected targets; rollback failures.
Leave the parent modified. Save/check-in and BOM synchronization remain explicit.
No automatic revision adoption, child writes or geometry merge is introduced.

### Usage

1. Activate a managed Working assembly, acquire its checkout, then save/upload it.
2. Select direct component occurrences. Select occurrences of one item/revision at
   a time; with no selection, the command asks which component group to inspect.
3. Choose occurrences in the checklist. Already-current occurrences are skipped.
4. Review the exact old/new snapshot IDs, timestamp and hash; approve the update.
5. Inspect geometry/joints. Check in the assembly to publish the new exact pins.
   The command itself does not save or release your checkout. BOM synchronization
   remains separate; same-revision snapshot adoption does not change BOM quantities.

Newer revisions still use **Replace with New Revision…**. Missing object names,
changed object types, unsupported link dependencies and unsafe generated-child
joint mappings require manual resolution. Geometrically changed faces can keep
the same names; inspect engineering meaning even when structural checks pass.

Validation: 251 addon tests and 22 real FreeCAD/HTTP two-user checks passed, plus
native AssemblyLink same-revision update and generated-child joint rollback probes.
Evidence: [component update report](validation/freecad-component-update-2026-11-03.json).
