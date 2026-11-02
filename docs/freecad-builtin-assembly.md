# Native Assembly BOM adapter — addon 0.4.2

## Problem and supported mapping

The native Assembly workbench stores a container as `Assembly::AssemblyObject`,
with component links and joint/control objects. The original Phase 4 adapter
rejected every `Assembly::` object and every Python proxy. This prevented BOM
extraction even when all engineering components were supported whole-object links.

Addon 0.4.2 recognizes one exact `Assembly::AssemblyObject` per document, with
direct whole-object `App::Link` members. A standard `Assembly::JointGroup` and
its `JointObject.Joint` / `JointObject.GroundedJoint` members are excluded from
engineering occurrences. Shared membership of a joint in both assembly and joint
group does not produce duplicate quantities. Each selected component link counts
once; repeated internal links retain the existing exact-revision grouping policy.
Linked external subassemblies remain direct components, without flattening.

This is a bounded structural adapter. It does not run or modify the assembly
solver, ground objects, alter joints, or infer engineering components from labels.
Nested/multiple local native assembly containers, indirect component groups,
links outside the native container, custom container/joint-group proxies, unknown
joint proxies, link arrays and unsupported assembly types are rejected with
object-specific errors. Other Assembly features and Assembly3/Assembly4 are not
certified. Existing generic App::Link/plain-group handling remains available for
documents without native assembly containers.

The adapter retains existing root/child upload hashes and exact dataset/file/
object checks. Checked-out component copies must be uploaded first and then their
parent. The new adapter does not bypass these checks, acquire checkouts, perform
automatic uploads, or synchronize without the existing selection/review consent.
No backend/API/schema change is required.

## Reference and implementation boundary

The container/group and proxy identities were checked against the actual loaded
FreeCAD **1.1.4** objects and the official FreeCAD **1.1.0** source:

- [Native assembly creation](https://github.com/FreeCAD/FreeCAD/blob/1.1.0/src/Mod/Assembly/CommandCreateAssembly.py)
- [Joint and GroundedJoint definitions](https://github.com/FreeCAD/FreeCAD/blob/1.1.0/src/Mod/Assembly/JointObject.py)

These are identity/structure references; no upstream source was copied. Assembly
joint objects constrain geometry and are not engineering BOM components. This
extends ADR-005's bounded client adapter while preserving the separate immutable
CAD reference graph and authoritative server engineering BOM.

## Validation

Automated addon suite: **131 passed**, including native containers, standard
joint exclusion, duplicate joint membership, unknown proxies/types, stray links,+nested local assemblies and the prior generic-link/packaging regressions. Addon
lint/format and package validation pass.

Live testing used the user's explicitly authorized open test assembly **A000001
Rev A**, Linux FreeCAD **1.1.4**, Python **3.11.14**, Qt **6.8.3**, real dialogs and
HTTP. Its two children had been forked into checked-out working copies but had
not yet been uploaded. The initial root upload was correctly rejected. Existing
files were backed up in `/tmp`; both owned Working components were uploaded first,
then their parent, through the actual Upload command. No checkout was stolen or
released and no lifecycle transition was performed.

The actual **Show BOM → Synchronize from CAD** workflow then selected the two
component occurrences and approved replacement of the empty engineering BOM.
The saved result is **P000004 Rev A × 1** and **P000005 Rev A × 1**. Reopening the
actual Show BOM dialog displayed both lines. Synchronization preserved all open
CAD file hashes, native assembly membership, component placements and the grounded
constraint, and restored toolbar actions. See the **15 live checks** in
[the report](validation/freecad-native-assembly-bom-2026-11-01.json).

The reproducible harness is `clients/freecad/tests/freecad_native_bom_smoke.py`.
It requires an explicitly authorized test assembly with an empty BOM, owned
checkout and uploaded snapshots; it intentionally writes the reviewed BOM. Its
`read_display(App, Gui)` helper only reads the actual Show BOM dialog. Final
success/error notifications were captured to avoid blocking the harness; selection
and consent dialogs ran normally with automated input. Both installed profiles
were backed up outside `Mod` and updated to 0.4.2; the active CAD module was reloaded
in the current session. Other FreeCAD versions and platforms remain unverified.

## Native subassembly BOMs — addon 0.5.5

Synchronization captures the immediate parts (`App::Link`) and subassemblies
(`Assembly::AssemblyLink`) of the native assembly container. Each subassembly
links a whole external `Assembly::AssemblyObject`. Its generated local child
links and joint groups are excluded from the parent's engineering occurrences.
A generated member cannot also be a direct component of the parent. Stray links,
local nested assembly containers, missing/subelement targets and arrays remain
unsupported rather than being silently counted.

Repeated direct occurrences group by exact component revision. Each assembly
revision owns its own immediate BOM; synchronization does not descend into source
subassembly documents or write their BOMs. Multilevel reads expand the stored
revision-pinned child BOMs through the existing recursive backend endpoint. A
child assembly whose BOM has not been synchronized has no expanded child lines.
This differs from flattening the CAD dependency manifest, which also records
references needed to reconstruct the native file and is not an engineering BOM.
No backend/schema change is needed; selection, review, uploaded snapshot checks,
checkout ownership and concurrency tokens remain in force.

Validation: 178 addon tests passed, including mixed direct parts/subassemblies,
repeated subassembly aggregation and invalid membership/target cases. Lint,
manifest check and distribution build passed. In live FreeCAD, A000002 Rev A
produced exactly one candidate: A000001 Rev A, quantity 1; its seven projected
part links were excluded. Real HTTP preparation verified the uploaded pins.
The existing empty BOM and all open document file hashes were preserved; final
BOM replacement remains available through the ordinary selection/review dialog.
See [the live report](validation/freecad-native-subassembly-bom-2026-11-02.json).
