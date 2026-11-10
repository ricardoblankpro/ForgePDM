# Standard-part mass: supplier, CAD estimate and manual

Addon **0.11.0** uses backend **schema 16** (no new migration). It adds CAD/manual
fallbacks to the supplier-reference support introduced in 0.10.0. Mass belongs to
the exact S revision in existing Standard Parts workflows. No extra required registration fields are added.

Register an S fastener through the existing FreeCAD Fasteners registration
workflow, choosing its full material/class/finish specification. Registration
attempts to retrieve mass after creating the item. The result is available in
its web **Description** tab as grams per piece with supplier, article, source
link and retrieval date. Selecting/reassociating an existing S fastener reuses
its saved reference, or attempts lookup if you own its Working checkout.
When no supplier mass is saved, FreeCAD estimates mass from the supported
fastener's solid volume and an explicit reference density for the selected
material. Unknown materials/invalid solids remain unavailable. Neither case
blocks registration or association. The UI labels the source **Supplier reference**,
**Estimated from CAD** or **Manual entry**; missing values never become zero.
Generic purchased items without structured specifications remain supported but
cannot be automatically matched by this adapter.

Released S mass records of every source are immutable. To add mass to an older Released S with no
reference, create its next revision, then use **Find reference mass** in the web
Description tab while holding its checkout. Existing assemblies retain their
original exact S revision pins. Do not silently replace them with the new revision.
New S revisions copy saved reference mass. Saved S data contributes to
[assembly mass totals](assembly-mass.md), including explicit CAD estimate warnings.

## CAD and manual fallbacks (0.11.0)

For a known material, register or associate a native Fasteners object normally.
The addon reads its valid single solid's `Shape.Volume` in mm³. The backend computes
`mass_kg = volume_mm3 × reference_density_kg_m3 / 1,000,000,000`. It records the
BRep hash, reference card, volume, generator version and whether threads were
simplified, modeled or unknown. No shape/material/placement is changed. The
backend validates the arithmetic and specification; the CAD client measures the
volume. This estimate is not a supplier measurement or a CAD dataset/file pin.

Reference densities are frozen factual values from FreeCAD 1.1.4 standard cards:

| Selected S material | Reference card | kg/m³ |
|---|---|---|
| steel | Steel-Generic | 7900 |
| carbon steel | Steel-C15 | 7800 |
| alloy steel | Steel-20NiCrMo2 | 7800 |
| stainless steel A2 | Steel-X5CrNi18-10 | 7800 |
| stainless steel A4 | Steel-X5CrNiMo17-12-2 | 7800 |
| aluminium / aluminum | Aluminum-Generic | 2700 |
| copper | Copper-Generic | 8960 |

These are explicit approximation surrogates, not certified fastener-alloy
properties. Other values (including Unknown and unrecognized legacy text) have
no default density. Thread simplification, actual alloy and coatings can change
real mass. A saved estimate is reused per S revision; toggling thread display does
not overwrite it or make assembly-wide updates.

To enter a measured/datasheet value during native fastener registration, expand
**Enter mass manually if no supplier match**, enter **Mass per piece (g)** and an
optional note. The field is optional; blank unchecked controls change nothing.
An available supplier reference is retained. Otherwise manual entry takes priority
over the automatic estimate. Generic purchased-item registration remains simple;
its manual value can be entered afterward in the web UI.

For an existing checked-out Working S revision, open its web **Description** tab,
expand **Enter mass manually**, enter grams and optionally a note, then **Save
manual mass**. It can replace an estimate or an earlier manual value, including
for unknown materials and generic S items. A stale token rejects concurrent edits.
A saved supplier reference cannot be replaced by a fallback. Automatic estimation
never overwrites an existing manual value. **Find reference mass** may upgrade an
owned Working estimate when a verified supplier/CSV record becomes available;
otherwise it preserves the estimate. An explicit manual value stays in place.

Unchanged/retained fastener associations are considered during Upload/Check In,
so existing Working S revisions can gain missing estimates without reassociation,
provided you own their checkout. Released S items need a new revision for edits;
no new revision is created automatically. Assembly mass totals are now available; see [usage](assembly-mass.md).

## Initial live lookup coverage

The Fabory adapter has explicit candidate families:

| Standard | Material | Class | Finish |
|---|---|---|---|
| ISO 4017 / DIN 933 | Steel | 8.8 | Zinc plated or yellow passivated zinc |
| ISO 4032 | Steel | 8 | Plain or zinc plated |
| ISO 4762 / DIN 912 | Steel | 10.9 | Plain |
| ISO 4762 / DIN 912 | Stainless A2 | A2-70 | Plain |
| ISO 7089 / DIN 125-1A | Steel | 200 HV | Zinc plated |

Integer metric diameters and ordinary integer lengths are supported. Availability
varies by product and region. A candidate article is never accepted without
checking the returned product page. Missing fields, changed pages, unknown
material/class/finish, custom pitch/dimensions, left-hand threads, redirects,
blocked access or network failure leave supplier mass unavailable; CAD/manual
fallbacks may still supply a value. A plain `DIN125` record
is not automatically treated as `DIN125-1A`. `Carbon steel` and `alloy steel` are
not silently matched to a supplier's less-specific `steel` designation.

Fabory's public robots policy disallows automated search pages and -sku paths;
this adapter does not use them. It reads only specific allowed public product
pages after checking the policy. It is not an official Fabory API or a guaranteed
bulk-data feed. Failed attempts have a one-hour per-revision cooldown. Existing
saved mass is reused immediately. Set `FORGEPDM_SUPPLIER_LOOKUP=0` on the backend
to disable live access; CSV matching continues to work.

## CSV reference feeds

Administrators can import a CSV from an S revision's Description tab. Each row
must have these exact columns (order does not matter):

```text
specification_json,supplier,source_article,source_url,mass,unit,quantity
```

`specification_json` contains the existing standard specification contract,
including geometry, material, grade and finish. Quote JSON cells using normal
CSV escaping. `mass` is the mass of `quantity` pieces; units are `g` or `kg`.
Quantity must be an integer from 1 to 1,000,000. For example, `1.6,kg,100` becomes
`0.016 kg` per piece. Source URL must use HTTPS. Import only data with verified
units and specifications. File limit is 1 MiB/5,000 unique specifications.

See [the example CSV](examples/supplier-reference-mass.csv). It contains one
small factual example, not a complete supplier catalog. Imported data has priority
over live lookup. Select **Find reference mass** to adopt it on an owned Working
revision; imports never rewrite already saved references or Released revisions.
Invalid rows and duplicate specifications reject the entire import. Different
material/finish/class/geometry keys never match by description alone.

## API

- `GET /api/v1/revisions/{id}/reference-mass`: read the saved reference/unavailable.
- `POST /api/v1/revisions/{id}/reference-mass/lookup`: reuse or attempt enrichment.
- `PUT /api/v1/revisions/{id}/reference-mass/fallback`: optimistic manual/CAD estimate save.
- `POST /api/v1/reference-masses/import`: administrator JSON `{csv_text: "..."}`.
- Structured S `POST /api/v1/items` adds a `reference_mass` result automatically.
- Standard Parts capabilities include `reference_mass_version=1` and `mass_fallback_version=1`.

Provenance includes the exact specification key, original quantity/unit, kg per
piece, supplier article and source date. A supplier reference is not an individual
measured weight or an automatic purchasing commitment. No inventory, costing or
ERP integration is performed.

Fallback writes use `{method:"manual", mass_g:"12.5", note:"Measured", expected_token:"..."}`
or the CAD estimate contract returned by the addon. `GET reference-mass` includes
its optimistic `token` and optional `estimate_context`. Existing supplier fields
are retained. No M item or full native material-card assignment is required for
S mass. See [ADR-016](decisions/ADR-016-standard-part-mass-fallbacks.md).
