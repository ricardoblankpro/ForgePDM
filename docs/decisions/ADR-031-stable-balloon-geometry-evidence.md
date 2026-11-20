# ADR-031 — Persistence-stable automatic balloon evidence

Status: accepted, 2026-11-20, following the owner's request to fix the reproduced
geometry-fingerprint failures. Extends [ADR-030](ADR-030-automatic-balloon-attachments.md).

## Problem and decision

Raw `exportBrepToString()` hashes include OCCT processing flags and insignificant
numeric differences. A live assembly can therefore fail the exact pinned PDF
configuration loader even when its component revisions, arrows and engineering
geometry are unchanged. Simple native-box acceptance did not cover the actual
Fasteners/transforms/reconstruction sequence. See the
[investigation](../validation/balloon-fingerprint-investigation-2026-11-20.json).

New automatic links use binding version 3 and table format 7. Their geometry
evidence declares fingerprint profile `occt-brep-q12-v1`. The adapter supports the
known OCCT ASCII topology formats V1–V3 and verifies the topology-record/flag count.
It normalizes whitespace and serialized real numbers to 12 decimal places, with
decimal half-even rounding, and masks the Free/Modified/Checked processing flags.
It retains all topology references, subshape orientations, the four geometric flags,
surface/curve data, tolerances and placement transformations. Original CAD geometry
and serialized files are not rewritten by fingerprinting. Unsupported/malformed
formats and out-of-range numeric data fail closed.

The numeric grid is 1e-12 in serialized coefficient units, not a general geometric
distance threshold. This is a conservative persistence fingerprint, not a complete
geometric-equivalence theorem: topology reordering or values straddling a rounding
boundary can still require explicit relinking. The test scope is the recorded
runtime, including the user's transformed Fasteners and exact PDF-source path.

All-view component membership/revisions remain checked. The selected occurrence
must still be hit by the physical arrow test; real shape/placement, source view,
arrow, scale/orientation or BOM identity changes retain their existing gates.
No distant-nearest fallback or silent adoption is introduced.

## Compatibility and reconciliation

Manual bindings remain version 1. Version-2 attachments retain the exact legacy
raw-text reader; they are not reinterpreted using a different hash. Formats 1–6
remain readable. New links upgrade their table to format 7; subsequent manual
links and table updates preserve that gate, so older addons reject unsupported edits.
Unknown evidence profiles and binding/table inconsistencies are rejected.

An old one-way hash cannot reconstruct its baseline geometry. Explicit relinking
uses the normal lifecycle, managed-working-copy, edit-permission and live-owned-
checkout guards and creates current version-3 evidence. A user-authorized rebaseline
to an existing target additionally verifies the original frozen BOM identity,
unchanged arrow/view fields and occurrence/revision set, and a current arrow hit on
that exact component. It never guesses a replacement target, clears unresolved
bindings, changes BOM numbering or converts automatic links to manual. Such a
rebaseline is never invoked by restoration, inspection or PDF preflight.

No backend, schema, server snapshot, publication-journal or lifecycle contract changes.
Save/upload/publication remain explicit actions.

## References and licensing

The independently written adapter follows the official
[OCCT BREP format](https://github.com/Open-Cascade-SAS/OCCT/wiki/brep_format) and
[OCCT 7.8.1 shape serialization source](https://github.com/Open-Cascade-SAS/OCCT/blob/V7_8_1/src/TopTools/TopTools_ShapeSet.cxx).
The latter is LGPL-2.1 with the OCCT exception; it was consulted, not copied into
the addon. Existing project licensing boundaries are unchanged.
