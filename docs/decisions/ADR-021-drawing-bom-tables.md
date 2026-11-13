# ADR-021 — Frozen direct engineering BOM tables in TechDraw

Status: implemented first increment, 2026-11-12, user authorized.

Generate a direct-component drawing report through a read-only HTTP endpoint.
Read parent identity, exact BOM revision pins, descriptions and available P/S mass
sources inside one database snapshot. Return all lines or fail authorization;
never substitute latest component revisions. Hash the report evidence separately
from its generation timestamp. No schema change or engineering writes.

The addon renders a self-contained SVG in a native TechDraw DrawViewSymbol.
Store report values, evidence token, layout and custom text in its PDMTableData
string property, format 1. This keeps the drawing portable and readable offline,
without Python proxies or external image files. Explicit Update fetches new values;
restore/recompute never performs HTTP or rewrites the table. Native save/reopen,
managed upload/retrieval and PDF export are validated before delivery.

Default columns are position, item number, revision, quantity and Description /
Material, respecting existing P/A/S semantics. Layouts configure column fields,
headings, order, widths, alignment, text size, mass units/precision and custom text.
Native Qt font metrics determine wrapping; reject page overflow before applying.
Persist named layout definitions locally in FreeCAD preferences, without row data.
Store each drawing's actual layout/data in the FCStd file as well.

Custom text is keyed by exact component revision plus stored BOM position and
column identity, not visual row index or unstable BOM database line UUIDs.
Quantities can change without losing annotations. Changing a component revision
or position does not apply another row's text; retain orphaned text in the saved
map for recovery. This also handles normal BOM replacement/copy-forward creating
new line IDs. Do not automatically renumber positions; balloon integration is later.

Require a managed working copy, Working lifecycle, current edit permission and an
owned unexpired checkout. Revalidate report token, checkout ID/version, document,
session, target table and page after review. Do not save/upload or synchronize the
BOM automatically. Use a native undo transaction for table changes and preserve
other edits. Block active CAD edit mode; normal pending property transactions
follow FreeCAD's normal transaction handling rather than preventing insertion.

Unknown mass is unavailable, never zero; CAD estimates retain a visible ~ marker.
First-increment unit/extended masses cover direct P/S lines. Subassembly unit mass
is unavailable in this report; avoid independently re-querying rollups outside
the snapshot. Default columns do not include mass. Direct rows retain independent
positions and decimal quantities, including repeated exact revisions.

No flattened/indented tables, multi-sheet splitting, CAD-property mapping, balloon
links or automatic stale-table publication/release gate in this increment. User
must explicitly refresh drawing data before publishing changes. Released native
snapshots remain unchanged. Header text is configurable; the title/font family
are currently fixed. Presets are local to the FreeCAD profile.
