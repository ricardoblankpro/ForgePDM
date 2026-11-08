# Supplier reference mass

Addon 0.10.0 and backend migration 16 add optional reference mass to existing
Standard Parts workflows. No extra required registration fields are added.

Register an S fastener through the existing FreeCAD Fasteners registration
workflow, choosing its full material/class/finish specification. Registration
attempts to retrieve mass after creating the item. The result is available in
its web **Description** tab as grams per piece with supplier, article, source
link and retrieval date. Selecting/reassociating an existing S fastener reuses
its saved reference, or attempts lookup if you own its Working checkout.
Unavailable or mismatched data does not block registration or association.
Generic purchased items without structured specifications remain supported but
cannot be automatically matched by this adapter.

Released S references are immutable. To add mass to an older Released S with no
reference, create its next revision, then use **Find reference mass** in the web
Description tab while holding its checkout. Existing assemblies retain their
original exact S revision pins. Do not silently replace them with the new revision.
New S revisions copy saved reference mass. Assemblies do not yet calculate total
mass; this increment supplies the revision-bound S data for that future feature.

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
blocked access or network failure leave mass unknown. A plain `DIN125` record
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
- `POST /api/v1/reference-masses/import`: administrator JSON `{csv_text: "..."}`.
- Structured S `POST /api/v1/items` adds a `reference_mass` result automatically.
- Standard Parts capabilities include `reference_mass_version=1`.

Provenance includes the exact specification key, original quantity/unit, kg per
piece, supplier article and source date. A supplier reference is not an individual
measured weight or an automatic purchasing commitment. No inventory, costing or
ERP integration is performed.
