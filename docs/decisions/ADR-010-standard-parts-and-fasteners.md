# ADR-010: S numbering and embedded Fasteners occurrences

Status: implemented, 2026-11-05. See [usage and limits](../standard-parts.md).
Project-scoped registration below is superseded by
[ADR-011](ADR-011-shared-standard-parts-library.md) from migration 12.

S is an Item numbering series, not a structural kind. S items retain ordinary
part revisions, permissions, checkout and lifecycle. Migration 10 copies P/A
counter values into per-series counters; existing UUIDs/numbers remain intact.

Migration 11 adds immutable Item-level fastener identity specifications and
immutable dataset-level occurrence evidence. Specifications contain normalized
Fasteners geometry plus explicit material, grade and finish (unknown is allowed).
A different physical specification needs a different Item. Native geometry and
controlled representation updates remain revisioned. Complete normalized JSON is
unique within the registration project, or creator scope for projectless admin
items. Separate projects may intentionally register equivalent components.
Concurrent creation conflicts are explicit; a retry searches existing matches.
This is bounded specification matching, not supplier equivalence or certification.

The optional client adapter discovers FastenersCmd FSScrewObject descendants.
Direct Assembly members and document-root objects produced by the normal Fasteners
toolbar contribute to the sole assembly; nested local groups remain rejected.
Upload and Check In resolve associations before saving a new snapshot. Existing
exact revisions remain pinned; new groups require confirmation of purchasing
identity. Registration creates a normal checked-out Working revision, never an
automatic release. Confirmed registration survives canceled/failed CAD upload.
Each embedded occurrence carries an addon-owned UUID and association JSON with
adapter version, exact revision, normalized geometry and generator provenance.
Copying repairs duplicate occurrence IDs during preflight. Geometry edits invalidate
the association; cosmetic threads and placement do not determine purchasing identity.

The backend inspects bounded native XML without importing FreeCAD or unpickling
Python objects. It verifies saved parameter values against declared associations,
validates catalog geometry/read rights/lifecycle and inserts occurrence evidence in
the same transaction as the native dataset. Atomic check-in replay already binds
these bytes through the source content hash. Uploaded identity is an engineering
declaration, not proof that material/grade/finish can be inferred from CAD.

Embedded occurrences are engineering BOM evidence, not fake external dependencies.
Existing manifests expose this evidence separately. The optional
freecad-fasteners-v1 profile adds narrowly validated BaseObject references to one
Edge/Face/Vertex on an exactly pinned managed file/object. Original
freecad-app-link-v1 manifests remain compatible. Paths are rewritten before opening
files, and target subelements are checked during capture and reconstruction.
Local attachments through managed App::Link occurrences stay local; that link's
existing manifest pins its external file. A capability check prevents silently
using the new workflow against an older backend.

BOM proposals combine direct linked and embedded occurrences, grouping by exact
revision and preserving subassembly boundaries. Existing selection, replacement
review and concurrency tokens remain authoritative. Upload and Check In do not
write an engineering BOM. Referencing a library item grants no edit rights and
does not add the item to the assembly's project.

This reuses the Item/Revision/Dataset/BOM separation of ForgePDM's Teamcenter-inspired
model. It integrates public Fasteners behavior rather than copying its GPL source;
it does not adopt a separate CAD-side database or an EasyPDM-specific identity model.

Limits: no automatic semantic face remapping after topology changes, arrays,
arbitrary proxy support, supplier equivalence, automatic revision adoption or
production reliability claim. Legacy upload/manifest publication remains separate;
the source dataset and standard occurrence evidence publish atomically, while
atomic native Check In additionally publishes its manifest and checkout release.
Phase 5 legacy-write fencing/revision-creation retry debt remains separate.

## 0.7.3 registration presentation

The addon bundles controlled material/class/finish options and generates uppercase
catalog text in the user-selected TYPE MATERIAL FAMILY NORM DIMENSION GRADE FINISH
order. Filtering prevents obvious family/material mismatches; the registry is not
a certification engine or a full alloy/coating compatibility matrix. Unverified
stainless class pairs are not cross-joined. Extended options remain explicit.

This changes client presentation and new registration defaults, not the four-field
version-1 backend specification contract. Existing free-text API callers and stored
specifications remain valid; no data migration or automatic synonym merge is made.
Names/descriptions remain presentation, with UUID/specification-based identity.
Generic purchased items lack this fastener schema and retain their manual flow.
