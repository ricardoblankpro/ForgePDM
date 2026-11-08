# ADR-014: Physical material links and source-pinned part mass

Status: implemented in migration 15 and addon 0.9.0+, 2026-11-07.
Current addon 0.10.0 also includes the 0.9.1 legacy working-copy preparation fix.

Keep ADR-013's one M selection for P parts and assembly free text. Add native
FreeCAD registration (description + physical material) and curator-only linking
of existing M revisions. No new purchasing identity, stock-consumption workflow,
inventory or assembly-mass feature is introduced.

Backend remains independent of FreeCAD. Accept a bounded physical snapshot with
source UUID/name/density in kg/m³ and attribution. Store M links separately from
frozen P assignment snapshots; changing a Working M link cannot retroactively
change existing P assignments. New revisions copy the snapshot. Link edits use
normal Working checkout and optimistic concurrency; Released M entries require
an explicit next revision.

FreeCAD 1.1.4's Materials::PropertyMaterial serialization contains a UUID only.
Assigning an unregistered temporary material is not portable. Generate immutable
UUID-v5 density cards in the native User library under ForgePDM, using a hash of
the frozen snapshot. Retain original source UUID separately and never overwrite
source library entries. Regenerate missing managed cards from metadata before
opening a downloaded FCStd. The cache deliberately carries density only; complete
FEM/thermal/appearance card synchronization is outside this increment.

Calculate mass on final local solids, excluding intermediate features and managed
links; reject overlapping/invalid geometry as unavailable. Own-checkout geometry
recompute and native publication refresh the result. A changed native assignment
must be reconciled explicitly; unsupported/unlinked cases never report zero.

Publish physical snapshot, object volumes/native UUIDs, mass and reason with the
CAD dataset in the existing transaction/replay contract. Validate native XML UUIDs
and Decimal arithmetic on the backend, retaining the exact source hash. The CAD
client remains responsible for geometry measurement. Web displays latest uploaded
mass and marks changed assignments stale. Assemblies retain their description
workflow. Migration 15 is additive and does not backfill guessed physical links.
