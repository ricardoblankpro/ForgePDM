# Material and assembly descriptions

The normal workflow requires only a description. There are no mandatory density,
stock dimensions, consumption, allowance or material-readiness fields.

## Register a material

Open Item catalog → Register raw material. Enter one description, such as
`STEEL PLATE S235, 6 MM`, and register it. ForgePDM allocates the next M code in
the existing shared library. Existing library curators/administrators may create
or edit materials; enabled library readers may select them. Registered materials
are immediately selectable. Normal revision checkout/check-in rules still apply.

The Description tab edits the text of a checked-out Working M revision. Released
revisions remain immutable. A material needs only its description to be released;
no technical specification is required. Previous material specifications remain
stored and are not deleted by this simplification.

## Assign a material to a part

In FreeCAD, acquire an owned Working checkout and managed working copy for the P
part. Run **Assign Material / Set Description…**, choose Select material and pick
an M item. The current usable material revision and description are pinned at
selection. No solid selection, quantities or physical properties are required.
Clear material removes the assignment. Upload or Check In publishes the change.

You can also use the web revision's Description tab: search raw materials and
select one. The search only returns M items. Selection saves the description and
exact material revision to the checked-out engineering revision.

## Describe an assembly

For A assemblies, the same FreeCAD command opens a single free-text description
field. For example: `General mounting`. An empty value clears the description.
The web Description tab provides the same text field. Assemblies do not select
M records.

## Tree display and persistence

The FreeCAD tree has one **Description** column beside the existing PDM status
column. It shows raw-material descriptions for parts and free text for assemblies.
Linked components resolve their exact source engineering revision. Existing
item/revision/occurrence labels are unchanged. Unassigned records display blank.

A local description change is undoable and becomes part of the managed FCStd
metadata. Native upload/check-in validates and publishes it with the dataset in
one transaction. A conflicting web edit fails explicitly instead of overwriting
it; run the description command again to select the intended current value.

New engineering revisions copy descriptions and material pins. Changing an M
catalog entry does not rewrite previously assigned part descriptions. Download
reconstruction carries the engineering revision's saved description into isolated
configuration copies, preserving source files and historical revision pins.

Physical links remain optional for existing description-only records. The
saved `PDMDescription` and revision description API provide the information for a
future TechDraw BOM table; drawing BOM generation is not implemented here.

## Linked physical materials and part mass (0.9.0)

In FreeCAD, **Register Raw Material…** has two choices: catalog description and
physical material. The picker reads the native FreeCAD library and shows only
materials with valid density. Density is displayed read-only; no manual units,
stock dimensions or consumption fields are required. Registration creates the M
item, initial description and physical link atomically using library permissions.

For an existing web-created M entry, use **Link Physical Material…**. A Working
revision requires an owned checkout (the command acquires one if none exists).
A Released M entry requires explicit confirmation to create its next revision.
Cancellation does not create records or acquire checkouts. Existing part revisions
are not automatically remapped; select the M entry again to adopt a new link.

**Assign Material / Set Description…** still needs only one M selection on a P
part. Linked entries apply a native material snapshot to final local solids and
calculate mass. Intermediate PartDesign features and construction dependencies
are excluded; overlapping/invalid final solids report mass unavailable. Assemblies
continue using free text; assembly mass totals are outside this increment.

The read-only metadata properties **PDMPartMassKg** and **PDMPartMassStatus** show
local mass. An owned working copy updates them after geometry recompute. Upload
and check-in recompute before saving and verify native assignment; a manually
changed material must be reconciled through Assign Material. Clearing the material
removes the managed density and makes mass unavailable rather than zero.

Mass in kg is final volume in mm³ × density in kg/m³ ÷ 1,000,000,000. Server-side
checks validate source-native material UUIDs, pinned density and this arithmetic;
the CAD client supplies final geometry volumes. Published mass is tied to its
exact dataset/file hash. The web Description tab shows the physical name/density
and latest uploaded mass. Changing the engineering material invalidates the shown
uploaded mass until updated CAD is published. Local unsaved mass is not silently
published to the server.

FreeCAD 1.1.4 saves native material references by UUID. ForgePDM therefore freezes
the source UUID/name/density/attribution and creates a deterministic native density
snapshot card under the active User material library's `ForgePDM` directory. Cache
cards are immutable and exclude external paths or material inheritance. Download
reconstruction registers the card from saved metadata before opening the FCStd;
missing original library entries do not require guessing a replacement. Existing
native library cards are never overwritten. Cache cards show a `(ForgePDM)` suffix.
This increment preserves density for mass; it does not synchronize the source
card's FEM stiffness/thermal models or appearance properties.

Backend migration 15 adds physical-link, frozen part-assignment and immutable
mass-evidence tables. It does not infer links or mass for existing records.
Description-only registration remains available on the web. Parts without a linked
material display mass unavailable even if FreeCAD has a default physical material.

## API and compatibility

- `GET /api/v1/revisions/{id}/description` returns description,
  `material_revision_id` and concurrency token.
- `PUT` to the same endpoint accepts those fields with `expected_token`.
- `GET/PUT /api/v1/revisions/{id}/physical-material` reads/updates an M link with a concurrency token.
- `GET /api/v1/revisions/{id}/mass` returns source-published mass or an unavailable reason.
- `POST /api/v1/items` accepts an optional `physical_material` snapshot for atomic M registration.
- `GET /api/v1/materials/capabilities` advertises `physical_material_version=1`.
- `GET /api/v1/revisions/{id}` also includes `description_record` for CAD retrieval.
- Native files use versioned `PDMDescriptionData` metadata and projected
  `PDMDescription`. Dataset description evidence is immutable.

The normal interface no longer exposes the advanced material/BOM/requirements
workflow. Its previous records, native fields and API contracts remain available
for compatibility. Simple native metadata supersedes legacy material proposals
without deleting their stored evidence. No quantities are inferred from selecting
a material.

## Deployment and testing

Backend migration 14 is additive: it creates description/evidence tables and
seeds descriptions for existing M revisions using their prior specification
text, item description or item name. It does not assign materials to existing
parts or modify historical P/A revisions. Back up SQLite, storage and installed
addons before starting an upgraded backend. The current addon is **0.11.0** and
requires the backend through **migration 16**; physical links/mass originated in
migration 15. See [the upgrade checklist](upgrade-and-validation.md).

Addon 0.9.1 and later repair matching legacy description-only working copies
during upload/check-in preparation, applying their saved physical snapshot and
building missing native mass evidence. No reselection is required for that
compatibility repair. Different local descriptions/material pins remain pending
and retain concurrency protection. Adopting a newly linked M snapshot remains an
explicit material selection.

Automated coverage includes description-only material creation/release,
M-only selection, assembly text, clear, authorization, optimistic conflicts,
revision copying and atomic native replay. The real acceptance harnesses are
`tests/web/materials-browser.mjs` and
`clients/freecad/tools/validation/simple_descriptions_gui.py` and
`clients/freecad/tools/validation/physical_materials_gui.py`. They use disposable
fixtures and preserve the user's existing documents.

S purchased fasteners use [supplier reference mass](supplier-reference-mass.md),
separate from P geometry-derived mass. Both paths now feed
[assembly mass totals](assembly-mass.md). The original advanced material-input design is retained as historical
compatibility scope in ADR-012; ADR-013 defines the current simple workflow.
