# Assembly mass (addon 0.12.0)

Open an assembly's **Description** tab in the web interface, or **Show ForgePDM
BOM** in FreeCAD. The backend multiplies quantities through the stored engineering
BOM, using its exact component revision IDs. Repeated subassemblies contribute
once per occurrence; their geometry is never counted again on top of their children.

P components use the latest uploaded native mass evidence for that pinned revision,
including the existing physical-material/description freshness checks. S components
use their saved supplier, manual or CAD-estimated mass, preserving provenance.
Fastener CAD estimates are explicitly marked in the result. No supplier network
lookup, CAD recomputation or checkout is performed by this read operation.

A complete assembly shows a total in kg. Any missing or stale component mass, or
an assembly without stored BOM lines, makes the total unavailable. A separate known
subtotal and each missing component's reason and accumulated quantity remain visible.
Unknown values never silently count as zero. The per-path breakdown includes source
dataset IDs/hashes for P and saved reference provenance for S.

The calculation represents the stored engineering BOM and published masses. Save,
upload and explicitly synchronize changed CAD occurrences before relying on it.
Unsaved CAD edits, unpublished geometry, manufacturing material inputs, packaging,
joints and construction objects do not independently add mass. This is a finished
assembly engineering total, not a gross raw-material requirement calculation.

Results are calculated on demand inside one SQLite read snapshot. Working child
revisions may change their published mass or BOM and thereby change subsequent
results, even when a parent is Released. This endpoint does not create an immutable
mass certificate or source-pinned historical rollup. Creating a newer child revision
does not change the parent's pins. No schema migration is required (schema 16).

## API

`GET /api/v1/revisions/{revision_id}/assembly-mass` requires authentication and read
access to the root and every traversed component. A forbidden child fails the entire
request, without exposing a partial breakdown. A non-assembly root, stored cycle or
exceeded traversal/numeric limit returns a conflict.

The response contains `mass_kg` (decimal string or null), `known_mass_kg`,
`status` (`complete`/`incomplete`), `basis` (`stored_engineering_bom`),
`contains_cad_estimates`, `components` and `issues`. Each leaf records its exact
revision, accumulated quantity, BOM-line-ID path, unit mass, extended mass and source.
Traversal is limited to 64 levels and 10,000 visits; individual quantities allow
32 significant digits with decimal magnitude between 10^-30 and 10^31.

The updated backend API is required for FreeCAD 0.12.0 Show BOM on assemblies.
Part Show BOM behavior remains unchanged. Refresh the web Description tab or reopen
Show BOM to recalculate after publishing component changes.

From addon 0.14.0, **BOM / Mass… → Refresh published BOM** refreshes in place.
Native and web mass displays use at most three decimal places; positive values
below 0.001 kg show `<0.001 kg`. Stored/calculated/API values retain full precision.
