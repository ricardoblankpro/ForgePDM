# Standard parts and Fasteners Workbench

Current addon **0.11.0** requires the backend through **migration 16**. The core
Standard Parts/Fasteners implementation originated in migrations 10–12; supplier
reference mass adds migration 16. M raw materials share the library introduced
for S items. Existing S numbers, specifications and revision pins are preserved.
Back up the database and file storage before upgrading; deploy the backend and
addon together. Existing P/A items and historical link-only manifests remain valid.
Migration 12 moves existing S item ownership into the shared library while preserving
item/revision IDs, names, CAD files, checkouts and BOM references.

## Standard and purchased items

S000001 identifies a standard/purchased part. It is an ordinary part with revisions,
checkout and lifecycle. Use **Register Standard / Purchased Part…** to create a
metadata-only item, then explicitly keep its checkout, check in metadata, or check
in and release. All S items belong to the shared **Standard Parts Library**.
There is no project prompt: an assembly references the same S revision from any
engineering project without copying it or changing its ownership.

Enabled users receive library viewer membership on migration or account creation.
Library editors/owners and global administrators can register and edit S items;
ordinary project editor access grants no library write rights. Existing S creators
receive initial library editor membership during migration. Administrators can
manage these memberships in the web project-management page. Explicitly revoked
access remains revoked unless the account is disabled and enabled again.

The library uses the existing project permission infrastructure and is excluded
from P/A creation pickers. It cannot be archived. Older API clients that submit an
engineering project for an S item are routed to the library and still need library
edit rights. Legacy duplicate S identities remain separate; new identical
Fasteners specification registration is rejected across the library.

**Create / Upload Current Document** also offers a standard/purchased part choice
for native CAD models. Search in **Download Item / Assembly** can be filtered to S
items. The web catalog provides a series filter and shows registered fastener
specifications. Metadata-only items are valid BOM components; CAD retrieval requires
an uploaded native dataset. Prepare supplier STEP models as managed native CAD first.

Two placed links to the same managed S revision contribute quantity two through
the existing reviewed BOM workflow. Creating an S item needs no dedicated generator
or supplier management module.

## Fasteners workflow

1. Insert fasteners using Fasteners Workbench. In a native Assembly, put them in
   the Assembly's direct members, or leave toolbar-created fasteners at the
   document root. Both count as direct components of the sole native assembly.
   Fasteners nested in other local groups remain unsupported.
2. Run Upload or Check In. ForgePDM groups new/changed fasteners by their geometry.
3. Choose the exact matching catalog revision and confirm its purchasing details,
   or choose **Register a new S item**. Registration shows material, mechanical
   class and finish dropdowns. Unknown values remain explicit; they are not
   inferred from geometry.
4. Continue upload/check-in. Associations are saved in the assembly snapshot.
5. Open Show BOM and explicitly synchronize from CAD. Select the occurrences,
   review quantities and all changes to existing/manual lines, then confirm.

Unchanged associations retain their exact revisions without another selection.
A dimensional/type change requires reassociation. Placement, offset and cosmetic
thread display do not change purchasing identity. Copied objects receive distinct
occurrence UUIDs during preparation; deleted objects no longer contribute quantity.
Confirmed S registrations remain available if assembly preparation is canceled or
fails; retry searches find them. Concurrent duplicate registration gives a conflict:
retry the operation and select the existing catalog entry.

New registrations remain Working. They must be explicitly checked in/released
before a parent can pass the established Released-component release rules. The
metadata actions in the registration command concern newly registered items;
existing metadata revisions can also be managed through the regular backend API.

## Supported boundary

Live validated on Linux, FreeCAD 1.1.4 and Fasteners Workbench 0.5.43:
ISO 4017 bolts, ISO 4032 nuts, ISO 7089 washers and ISO 4762 screws, plus a purchased
native S model inserted twice. Discovery uses the shared FSScrewObject inheritance
and parameter contract, rather than a whitelist of these standards. Other families
using that contract can be recognized but are not all individually certified.
New/unknown identity parameters require an adapter update, never silent guessing.

Supported attachment forms: unattached, local geometry, a local managed component
link, or a direct external managed object with one explicit Edge/Face/Vertex.
Qualified local native Assembly paths such as Body002.Hole.Edge5 are supported
from 0.7.1. Direct external BaseObject references still require a single unqualified
Edge/Face/Vertex under the existing manifest contract.
External references pin exact revision/dataset/file/object/subelement identities.
Retrieval requires a compatible Fasteners installation and rejects missing targets
or null subelement shapes. It does not remap faces after topology changes: inspect
attachments and joints when replacing component geometry. Arrays, linked occurrences
of embedded local fasteners and unrelated third-party proxies are outside this adapter.

BOM synchronization preserves linked subassembly boundaries. Hidden objects still
count when selected; labels and visibility never determine identity. The adapter
does not automatically flatten subassemblies or update the server BOM.

## Validation

Automated tests cover numbering/migrations, concurrent catalog creation, permissions,
metadata-only lifecycle, specification matching, snapshot evidence, atomic replay,
edit invalidation, copies, unknown proxies and mixed BOM counts. Live evidence is
recorded under docs/validation/standard-parts-freecad-2026-11-05.json.
See ADR-010 and ADR-011 for persistence and shared-library architectural tradeoffs.

To reproduce the live fixture, start a dedicated FreeCAD session with Fasteners,
then run `uv run python clients/freecad/tools/validation/standard_parts_server.py`
from the repository. This creates a disposable loopback server and a configuration
under `/tmp`. Through FreeCAD MCP execute the GUI fixture files in order:
`standard_parts_gui.py`, `standard_parts_failures.py`, `standard_parts_subassembly.py`
in that same validation directory. They automate dialogs but run real CAD and HTTP
operations. Stop the disposable server afterward. They are development fixtures,
not production-data migration tools.

## Change a selected fastener's purchasing specification

Select one or more direct Fasteners objects, then run **Change Standard Part
Association…** in the ForgePDM menu/toolbar. The parent must be a managed Working
assembly with your active checkout. Choose a matching S specification with the
required grade/material/finish, or register a new one. This does not edit the old
catalog item, move geometry, change attachments, save/upload CAD or write the BOM.

Occurrence UUIDs are retained and unselected fasteners keep their original
associations. The edit is one undoable transaction. Upload afterward, then review
BOM synchronization: identical-looking screws with different S revisions produce
separate lines. To split an initially identical group, associate a selected subset
first, then resolve the remaining objects during Upload.

The command rejects stale selections/associations, pending CAD transactions and
checkout loss during review. Confirmed catalog registrations remain even if a later
stage is canceled; they can be reused on retry.

## Controlled fastener registration and generated names (0.7.3)

Fastener registration uses one specification form. Known standards automatically
supply type/family, while unknown standards require explicit type and family
selections. Material filters the available mechanical classes and finish processes.
The extended-options checkbox exposes specialist/legacy entries. Built-in option
IDs are versioned in the addon; adding a new option currently requires a registry
update. This is not a complete product/diameter/coating conformity checker.

The form generates the catalog name and description with no text-entry prompts:

`TYPE MATERIAL FAMILY NORM DIMENSION GRADE FINISH`

Example: `SCREW CARBON STEEL HEX HEAD ISO4016 M12X70 8.8 ZINC PLATED`.
All text is uppercase and dimensions use X. Custom length, explicit pitch, left-hand
thread and other exposed identity dimensions remain visible when applicable. The
preview must fit the existing 200-character Item name limit; nothing is silently
truncated. Material/class/finish Unknown values and class Not applicable are distinct
from Plain/uncoated finish. No class or finish is guessed as a purchasing default.

Existing S names, descriptions and literal specifications are not rewritten or
merged. Matching still offers readable existing catalog entries, including legacy
free-text values. This form applies to Fasteners-driven registration; generic
purchased items without a geometry specification retain their manual naming flow.

Validation: docs/validation/standard-parts-form-2026-11-05.json records real Qt
form/HTTP registration checks on disposable data, including exact screw/nut/washer
names, dependent selections, cancellation and preservation of user documents.

Shared-library validation: start the same disposable server, then execute
`clients/freecad/tools/validation/shared_standard_library_gui.py` through FreeCAD
MCP. It verifies registration without a project prompt, library access, curator
promotion and reuse in two project BOMs while preserving the current CAD session.
Run it against a fresh disposable server; it registers synthetic records there.

## Supplier reference mass (0.10.0)

Structured S registration optionally retrieves a verified supplier mass without
adding required form fields. Association/reassociation reuses saved mass or
attempts lookup while you hold the S Working checkout. Supplier outages,
unsupported types and incomplete specifications leave supplier mass unavailable; they do
not block engineering work. Released S references are not changed. New revisions
copy their reference, and earlier assemblies keep their original revision pins.

The web Description tab shows grams per piece, source supplier/article/link and
retrieval date. Administrator CSV reference imports cover other validated sources.
Live lookup currently supports an explicit subset of Fabory families; Fasteners
recognition/BOM support is broader than supplier lookup coverage. Unknown grades,
material/finish values and custom geometry are never inferred or substituted.
See [coverage and reference-feed instructions](supplier-reference-mass.md) and
[ADR-015](decisions/ADR-015-supplier-reference-mass.md). Assembly mass rollup is
not yet implemented.

## Missing supplier mass (0.11.0)

Normal registration/association/upload can estimate a supported native fastener's
mass from its single solid and an explicit reference density for the selected S
material. Labels distinguish **Estimated from CAD**, **Supplier reference** and
**Manual entry**; unknown values never become zero. The optional registration
manual field and checked-out web Description tab accept grams per piece and a
note. Released values stay immutable, manual values are preserved, and verified
supplier data may upgrade Working estimates. No automatic estimate replaces a
saved supplier/manual value. See [fallback workflow and density table](supplier-reference-mass.md).
