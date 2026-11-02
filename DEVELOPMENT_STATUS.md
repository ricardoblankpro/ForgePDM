# Development status

## 2026-11-02 — General component replacement (addon 0.5.8)

- Added Replace Component menu/toolbar command with part/assembly-number or name
  search, explicit item/revision/snapshot selection and whole-object mapping.
  Uses the revision replacement engine; the newer-revision shortcut remains
  restricted to the same item. Mapping can change part names/feature types.
- Preserve selected occurrence UUIDs/placements and unselected targets; labels
  reflect the new item. Block direct self-item insertion and unselected internal
  link dependencies that would otherwise silently follow the replaced object.
  Existing checkout/lifecycle, review, joint validity and rollback checks remain.
- 212 addon tests passed; 34 isolated live workflow checks passed, including
  renamed-object cross-item replacement, search/mapping cancellation, grounding,
  unchanged source files and BOM, plus exact pins after separate explicit upload.
  Native different-item assembly replacement and constraint rollback probes passed.
- Both addon profiles updated with backups. Command registered in running
  FreeCAD; main toolbar/menu registration included for future startup.
  Actual A000001 invocation correctly rejected its missing checkout and preserved
  its references, clean state and original selection. No checkout was acquired.
- Evidence: docs/validation/freecad-general-component-replacement-2026-11-02.json
  and docs/validation/freecad-general-native-replacement-2026-11-02.json.
- Limits: native AssemblyLinks still require native Assembly targets. No joint
  remapping or automatic save/upload/BOM synchronization. Inspect changed geometry.

## 2026-11-02 — Explicit component revision replacement (addon 0.5.7)

- Added Replace with New Revision menu/toolbar command. Select direct component
  occurrences, a newer revision and an exact uploaded native snapshot, then review.
  Require clean Working parent, managed working copy and owned checkout.
- Replace link targets in place in one undoable transaction with tree labels.
  Preserve occurrence UUIDs, placements, unselected targets and valid joint links.
  Reject missing/type-incompatible targets and unsafe joint mappings; rollback
  detected failures. Does not save/upload or synchronize BOM automatically.
- 201 addon tests passed; lint, manifest and distribution build passed.
  Twenty-six live isolated workflow checks cover cancel, one-of-two
  replacement, grounding, later explicit upload pin verification and rollback.
  Native subassembly replacement and generated-child constraint rejection tested
  in disposable documents. Actual registered command checklist/cancel tested on
  A000001 without replacing its components.
- Both installed profiles updated with backups. Runtime command/menu/toolbar
  registered; normal future startup adds it to the main ForgePDM toolbar.
- Limits: same internal target object names/types required. Changed face semantics
  cannot be inferred from names; inspect geometry/joints before saving. Native
  generated-child joint mappings may need manual work. Phase 5 atomicity unchanged.
- Design and usage: docs/component-revision-replacement.md and addon README.
  Evidence: docs/validation/freecad-component-replacement-2026-11-02.json and
  docs/validation/freecad-native-replacement-2026-11-02.json.

## 2026-11-02 — Live revision isolation (addon 0.5.6)

- Fixed New Revision mutating the live source document: new revisions now open
  distinct verified working-copy documents, leaving incoming assembly links,
  source metadata, geometry and paths unchanged. Clean/latest Released source
  guards prevent discarding unsaved edits or revising from stale geometry.
- Show BOM reports newer revisions separately while displaying the pinned
  revision; no automatic replacement, BOM update or background polling.
- 184 addon tests passed; targeted lint and manifest/build checks passed.
  Seventeen isolated live FreeCAD/HTTP checks passed, including editing B while
  the existing parent still targets A with unchanged labels/geometry/source hash.
- Actual registered Show BOM dialog verified the pinned Rev A and its newer
  revision B notice; the dialog was inspected and closed without synchronization.
- Repaired A000001's two P000006 links using the recorded uploaded revision A
  pins and original occurrence registry. Local assembly saved cleanly with
  P000006-A|1 and |2; revision B file and stored BOM preserved. A000002's
  already-dirty open document was not saved or closed. Backups kept outside Mod.
- Both installed profiles updated; runtime command classes/client refreshed.
  ADR-007 records the decision. Evidence in docs/validation/freecad-live-revision-
  isolation-2026-11-02.json and freecad-revision-pin-repair-2026-11-02.json.
- Limit: creation/upload still span separate operations (Phase 5); update
  notices are checked on Show BOM, and component adoption is not automated.

## 2026-11-02 — Direct native subassembly BOMs (addon 0.5.5)

- BOM synchronization now captures direct parts and native AssemblyLink
  subassemblies, excluding their generated child links/groups from quantities.
  Repeated occurrences group by exact revision. Child assemblies retain their
  independent BOMs; no recursive CAD flattening or automatic child writes.
- Preserved uploaded snapshot/pin verification, selection/review, checkout and
  optimistic concurrency checks. No backend/schema changes.
- 178 addon tests passed; targeted lint, manifest check and build passed.
- Both installed addon profiles updated with backups; CAD adapter reloaded.
  Live A000002-A produced A000001-A x 1 only, passing real HTTP snapshot/pin
  preparation. All open file hashes and the stored empty BOM were preserved.
  User can complete synchronization through the normal selection/review UI.
- Evidence: docs/validation/freecad-native-subassembly-bom-2026-11-02.json;
  supported boundaries documented in docs/freecad-builtin-assembly.md.

## 2026-11-02 — Native AssemblyLink Python binding (addon 0.5.4)

- Reproduced the setLink binding failure on Assembly::AssemblyLink in a
  disposable live FreeCAD copy. Native references now use LinkedObject property
  assignment; rebasing clears/reassigns the property to invalidate cached paths.
  Reconstruction also uses property assignment for this native type.
- Live installed-code Save As probe preserved all eight exact reference paths
  and all 29 objects. 170 addon tests, targeted lint, package check/build passed.
- Both addon profiles updated with backups; running CAD module reloaded.
- Repaired the failed working copy in place and retried the registered Upload
  command successfully. A000002-A saved cleanly with all eight references
  validated and all generated child labels matching the source subassembly.

## 2026-11-02 — Native subassembly labels (addon 0.5.3)

- Generated AssemblyLink children now project their pinned source occurrence
  labels; only the inserted assembly receives a parent occurrence allocation.
  Source registries, link targets and previous allocation history are preserved.
- Live FreeCAD verification: all seven generated part labels matched their
  exact source occurrences (P000004-B, P000005-A, P000006-A), and the inserted
  assembly displayed A000001-A|1. Existing downloaded configuration was repaired
  in memory; its saved file hash remained unchanged. Normal refresh correctly
  required a working copy for persistent edits.
- 169 addon tests passed; targeted lint, package validation and build passed.
  Both installed profiles updated with backups. Native insertion observer now
  recognizes AssemblyLink. Native subassembly BOM support remains separate.

## 2026-11-02 — Native subassembly upload fix (addon 0.5.2)

- FreeCAD native insertion creates `Assembly::AssemblyLink`, which the exact
  `App::Link` checks previously skipped/rejected. Capture, rebasing, FCStd
  inspection and reconstruction now accept this explicit native link type.
  Subelement/array serialization checks remain enforced.
- Installed in both local addon profiles and reloaded in running FreeCAD.
  The actual registered Upload command succeeded for the open assembly,
  recording its subassembly link and seven generated child references.
  The document remained clean after upload. No credentials recorded.
- Validation: 167 addon tests passed; targeted lint, manifest validation and
  0.5.2 distribution build passed. Added capture, rewrite and rejection tests.
- Limitation: native AssemblyLink BOM synchronization/tree label projection
  remains outside the direct App::Link adapter. A live download roundtrip for
  this new native link type has not yet been validated. Follow up on generated
  child ownership before extending BOM counting; do not flatten subassemblies.


Updated after addon 0.5.1 was pushed to `master` in commit `2ac9c3e`.
This is a handoff for future sessions; verify the current checkout and runtime
before acting. Git history and the linked reports provide the detailed record.

## Current implementation

- Backend: FastAPI, SQLite, separate SHA-256 file storage, authentication,
  project permissions, Items/revisions/datasets, checkout leases, lifecycle,
  revision-pinned BOMs and immutable CAD dependency manifests.
- FreeCAD addon: **0.5.8**, modern `freecad.forgepdm` namespace; communicates
  through HTTP without importing backend business logic.
- Development-direction Phases 1–4 are implemented for the documented supported
  structures. Phase 5 (atomic check-in, fencing and idempotency) remains future
  work. The original MVP roadmap has different phase numbering: use the active
  development-direction table in [the roadmap](docs/roadmap.md).
- Live validation has used Linux FreeCAD **1.1.4**, Python **3.11.14**,
  Qt **6.8.3**. Other runtime/platform combinations remain unverified.

## Recent behavior and fixes

- Passwords accept at least four characters, including numeric passwords.
  Local CLI commands support password resets and role changes; see the README.
- Check-in does not prompt for a change note. An omitted note preserves the
  existing revision note. Creating a new revision still requires a note.
- Asynchronous commands refresh FreeCAD command activation when they finish,
  preventing the toolbar from remaining gray until another command runs.
- Show BOM displays the stored engineering BOM. CAD synchronization is a
  separate reviewed action: it verifies saved/uploaded snapshots and exact
  component revisions before proposing replacement lines.
- The bounded native Assembly adapter supports direct whole-object App::Link
  components and excludes standard joints from quantities. Unsupported layouts
  require an adapter; this is not general support for every assembly workbench.
- Tree labels use `ITEM-REVISION|OCCURRENCE`, for example `P000005-A|2`.
  Numbers are scoped to the immediate parent and exact component revision;
  persistent UUIDs and allocation history preserve surviving occurrences.
  Deleted indices are not reused. Display labels never determine PDM identity.
- Addon 0.4.3 changed reconstruction to GUI document save so the GUI Modified
  flag clears correctly. Version 0.5.1 additionally recomputes after tree-label
  projection: legacy FeaturePython metadata can remain Touched after a save.
  Both clean-state guards remain enforced; unresolved edits are not discarded.

## Latest validation

- **162 addon tests passed** after the 0.5.1 fix. The preceding 0.5.0 validation
  recorded **54 backend tests passed**; the latest fix did not change backend code.
- Manifest/package build and targeted lint checks passed for 0.5.1.
- The exact assembly snapshot that failed on retrieved component `P000005-A`
  was retried through the actual registered Download command in live FreeCAD.
  The root and three component documents opened cleanly, all four occurrence
  links used their exact pinned revisions, and previous open documents and file
  bytes were preserved. Dialog choices/notifications were automated; real CAD,
  worker and HTTP paths executed.
- Both local FreeCAD addon profiles were backed up and updated to 0.5.1.
  The running CAD module was reloaded. Do not assume a future runtime still has
  the same version, active documents, authenticated session or running services.

Evidence:

- [Legacy snapshot download](docs/validation/freecad-legacy-label-download-2026-11-01.json)
- [Tree labels and occurrence identity](docs/freecad-tree-labels.md)
- [Phase 4 BOM synchronization](docs/freecad-addon-phase4.md)
- [Native Assembly profile](docs/freecad-builtin-assembly.md)
- [Detailed runtime validation](clients/freecad/Documentation/validation.md)
- [Addon changelog](clients/freecad/CHANGELOG.md)

## Next session

1. Read root and applicable nested `AGENTS.md`, inspect Git status and recent
   commits, and confirm the user's requested scope. No next phase is currently
   authorized by this handoff.
2. For CAD issues, confirm installed addon/runtime versions and reproduce with
   the actual document structure. Distinguish mocked tests from live validation.
   Preserve existing edits, immutable snapshots and exact revision pins.
3. Propose the Phase 5 design before major architectural changes. Existing
   upload/check-in operations are not yet an atomic end-to-end transaction;
   retry/idempotency, checkout fencing and concurrency evidence remain priorities.
4. Track later operational work separately: crash-orphan reconciliation,
   backup/restore, production security, clean-start/platform acceptance and
   distribution gates. Refer to the roadmap rather than treating this prototype
   as production-ready.

## Verification commands

Run from the repository root:

```sh
uv run --project clients/freecad --extra dev pytest clients/freecad/tests -q
uv run --group dev pytest tests -q
uv run --project clients/freecad --extra dev python clients/freecad/tools/addon.py check
uv run --project clients/freecad --extra dev python clients/freecad/tools/addon.py build
```

Use the runtime harnesses documented in the validation guide when real FreeCAD
verification is required. Never store passwords or bearer tokens in this file.
