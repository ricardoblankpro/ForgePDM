# Materials and component mass

The ordinary workflow uses descriptions, with optional physical material links.
Stock dimensions, consumption and manufacturing-readiness fields are not required.

For source languages, translations and review, see [description languages](localization.md).

## Descriptions and physical materials

- **M:** Register Raw Material creates a shared-library description such as
  `STEEL PLATE S235, 6 MM`. Curators/admins register/edit; readers select. A
  description-only material can be released without a technical specification.
- **P:** In an owned Working copy, use **Assign Material / Set Description…** to
  select an exact usable M revision and freeze its description. Clear removes
  the assignment. Upload/Check In publishes native changes. The web Description
  tab also supports assignment under checkout.
- **A:** The same command edits free text, for example `General mounting`.
  Assemblies do not select M records.

Changing M text or its physical link does not rewrite previously assigned parts.
New engineering revisions copy descriptions and pins. To adopt a changed material
snapshot, select the intended M revision explicitly. Native/web conflicts require
reconciliation rather than silent overwriting.

FreeCAD registration can link an M item to a native material with valid density.
For an existing entry use **Link Physical Material…**. Released entries require
an explicitly confirmed next revision. No revision or checkout is created merely
by cancelling that choice. Description-only registration remains available.

## Manufactured part mass

A linked material supplies a frozen UUID/name/density/attribution snapshot.
FreeCAD measures valid final solid volume; the backend validates
`mass_kg = volume_mm3 × density_kg_m3 / 1,000,000,000`. Intermediate construction
features are excluded. Invalid/overlapping final solids leave mass unavailable.

Read-only metadata properties `PDMPartMassKg` and `PDMPartMassStatus` update during
normal recomputation in an owned working copy. Published mass is tied to the
exact uploaded dataset/file hash. A changed engineering assignment invalidates
published mass until reconciled CAD is uploaded. Clearing material makes mass
unavailable rather than zero; a default FreeCAD material is not an inferred link.

Retrieval rebuilds immutable density snapshot cards in the active FreeCAD User
material library's `ForgePDM` directory. Original cards are preserved. The
snapshot supports density/mass, not general FEM/thermal/appearance synchronization.

## Standard/purchased part mass

S mass is per piece on an exact S revision. Its Description tab identifies the
source: supplier reference, CAD estimate, manual entry or unavailable. Sources
follow these rules:

1. An existing supplier reference is retained. A fallback cannot overwrite it.
2. An explicit manual value stays in place; automatic estimation does not replace it.
3. With no higher-priority saved value, a supported single-solid Fasteners object
   can use a frozen reference-density estimate. Invalid solids or unknown
   materials remain unavailable.

Optional **Enter mass manually** accepts grams per piece and a note during
registration, or in the web Description tab on a checked-out Working revision.
**Find reference mass** can adopt an exact CSV/supplier match or enrich an owned
estimate. No match/network failure preserves ordinary registration and existing
values. Released mass is immutable; create another revision for changes. New
S revisions copy mass evidence, without changing consuming assemblies' pins.

CAD estimates record volume, BRep hash, generator/thread mode and density source.
They are approximations, not supplier measurements. Reference cards cover steel,
carbon/alloy steel, stainless A2/A4, aluminium and copper; unknown materials have
no default density. They do not require assigning an M item to the S fastener.

## Supplier lookup and CSV

Live Fabory lookup is bounded to explicit families: ISO 4017/DIN 933 steel 8.8
zinc variants, ISO 4032 steel class 8 plain/zinc, ISO 4762/DIN 912 steel 10.9 plain
or stainless A2/A2-70 plain, and ISO 7089/DIN 125-1A steel 200 HV zinc. Integer
metric dimensions are supported. Exact returned attributes must match; generic
or incomplete descriptions do not establish equivalence. It is not an official
supplier API. Set `FORGEPDM_SUPPLIER_LOOKUP=0` on the backend to disable live
requests while retaining CSV/manual/CAD sources. Failed attempts have a one-hour
per-revision cooldown. Availability depends on supplier responses and access policy.

Administrators import CSV through an S revision's Description tab. Required
columns, in any order:

```text
specification_json,supplier,source_article,source_url,mass,unit,quantity
```

Use exact geometry/material/class/finish JSON, normal CSV quoting, HTTPS source
URLs, `g` or `kg`, and integer quantity 1–1,000,000. Mass describes that many
pieces: 1.6 kg for 100 pieces is 0.016 kg per piece. The limit is 1 MiB and 5,000
unique specifications. Invalid/duplicate rows reject the import. Imported matches
have priority over live lookup; importing does not rewrite saved revision masses.
See the [example feed](examples/supplier-reference-mass.csv).

Both P published mass and S saved mass feed [assembly reports](bom.md). Advanced
material-input/requirements records remain supported by compatibility APIs; the
normal UI does not expose that earlier workflow or infer stock consumption.
