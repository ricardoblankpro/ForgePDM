# ADR-016: CAD estimate and manual S mass fallbacks

Implemented in addon 0.11.0; schema remains 16. Extends ADR-015, 2026-11-07.

Reuse revision_reference_mass rather than creating another item or mass identity.
Return explicit source statuses: supplier_reference, cad_estimate, manual, or
unavailable. Additive response fields carry a canonical optimistic token and an
optional estimate context (exact geometry plus versioned density reference).
Existing supplier payloads remain valid. No database migration is necessary.

Try supplier/CSV evidence first. If no mass is saved, a supported native Fasteners
solid can supply Shape.Volume and a BRep SHA256. The backend selects an explicit
reference density from the S material field, validates exact geometry/quantity
bounds and computes kg with Decimal. Store reference-card identity, volume,
thread representation and generator version. The client measures geometry; the
server validates arithmetic and identity fields, not the BRep shape itself. This
is an estimate, not file-pinned supplier/measured evidence. Do not assign or alter
a native material, placement, Fasteners geometry or S association to calculate it.

Use reviewed factual densities from FreeCAD 1.1.4 standard cards as explicit
surrogates for recognized materials. Unknown/unmapped values remain unavailable;
no fuzzy material, grade, coating or language translation determines density.
Do not infer coating mass or model missing threads. A simplified-thread shape is
labelled as such. Invalid/null/multiple-solid geometry cannot supply an estimate.

Add optional manual grams-per-piece in the existing native registration form,
with a collapsed control and optional note; generic/older items can use the web
Description tab. A manual entry explicitly replaces an estimate or unknown value
under a current token and owned Working checkout. Supplier references are
protected from fallback replacement. Automatic estimates never overwrite manual
or saved estimates. Lookup may upgrade an owned Working estimate to a verified
supplier reference; it must recheck for concurrent manual/supplier data before
writing. Failed lookups reuse saved estimates rather than discarding them.

Released revisions stay immutable; new revisions copy the complete mass record.
Readers reuse available values without writes. Audit fallback changes and supplier
upgrades with before/after provenance. Metadata-only S items may receive manual
mass even without a structured fastener specification. Registration/association
still succeeds when geometry, density, network or checkout prevents enrichment.

Native upload/association considers retained fastener associations as well as new
ones, coalescing mass work per S revision. It does not silently upgrade a component
revision or edit its purchasing specification. Existing saved estimates are reused
across occurrence/thread-display changes. Assembly totals, TechDraw BOM tables and
ERP synchronization remain separate increments.
