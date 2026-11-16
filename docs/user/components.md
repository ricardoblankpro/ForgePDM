# Standard and purchased components

P items identify manufactured/custom parts, A items assemblies, S items standard
or purchased components, and M items raw materials. All use the same permanent
Item/revision system. S/M records live in a shared library rather than belonging
to each consuming project. Library readers can select them; curators/admins can
register and edit them. Assemblies pin exact S revisions.

## Fasteners

Keep using native Fasteners Workbench insertion tools. ForgePDM discovers the
supported shared `FSScrewObject` parameter contract and associates occurrences
with S catalog records. During Upload/Check In preparation it reuses valid exact
associations, groups unresolved fasteners and offers matching records or
registration. Cancellation stops snapshot preparation; already confirmed catalog
registrations remain available for reuse.

Register a fastener with its geometry, material, mechanical class and finish.
Geometry alone cannot establish a purchasing specification. Common/Extended
choices distinguish Unknown, Not applicable and Plain/uncoated. The catalog name
is generated from the selected specification. Unverified combinations are not a
claim of conformity. See the [controlled vocabulary research](../development/references/fastener-options.md)
for sources and applicability limits.

Changing purchasing attributes requires explicit reassociation using **Change
Selected Fastener Association…**. Geometry changes invalidate incompatible
associations. Copied occurrences receive fresh identities. Existing specifications
and historical assemblies are not merged or remapped automatically.

## Purchased CAD models

Register an S item and upload its native model through the existing managed CAD
workflow. Insert a managed whole-object link using FreeCAD's native assembly
commands. Reusing the same S model preserves one identity across projects while
occurrences retain exact revision/dataset/file pins.

Catalog identity does not require CAD: metadata-only S items can be checked in
and released under normal lifecycle rules. Their presence in an assembly still
requires a supported associated occurrence for CAD-to-BOM extraction.

## Supported boundary

Normal document-root fasteners and direct members of one supported native
Assembly are engineering occurrences. Nested local groups, arrays and arbitrary
FeaturePython proxies are not general supported insertion layouts. Narrowly
qualified Fasteners BaseObject attachments are reconstructed only with the exact
managed target file/object/subelement evidence; this does not add general
subelement-link support. Missing or incompatible dependencies reject retrieval.

Supplier mass, CAD estimates and manual mass are optional enrichment described
in [materials and mass](materials.md). Missing mass does not block registration.
No supplier equivalence, stock, purchasing, costing or ERP synchronization is
inferred from catalog registration.
