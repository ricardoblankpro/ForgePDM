# Research: linked drawing BOM balloons

Historical research from 2026-11-18. Implemented decisions now live in
[ADR-029](../decisions/ADR-029-linked-drawing-balloons.md).

User-selected next work, 2026-11-18, deferred to the next session. This records
research and a proposed first increment; it is not an implemented feature or
approval of every design choice below. The user asked to investigate balloons
before changing BOM position/numbering behavior.

## Research findings

- FreeCAD already supplies native `TechDraw::DrawViewBalloon` graphics, leader
  positioning and editable text. The inspected FreeCAD 1.1.4 runtime matches
  [this upstream implementation](https://github.com/FreeCAD/FreeCAD/blob/4fd3bf320d9566a27e60069fc8387448aaa3a094/src/Mod/TechDraw/App/DrawViewBalloon.cpp).
  Its native properties do not associate a balloon with a ForgePDM BOM entry.
- A disposable native probe demonstrated that balloon `Text` can reference a
  document string property through an expression. Changing that property updates
  the text; the expression, table link and row identity survive native save/reopen.
  Sorting a table does not have to retarget the binding. This proves the native
  text mechanism, not a complete BOM resolver or geometry attachment system.
- The inspected drawing had two ForgePDM tables and three balloons containing
  literal text, without expressions or ForgePDM binding properties. Existing
  balloons need explicit adoption; their current number is not proof of a link.
  These are dated observations, not assumptions about the next session's state.
- Drawing tables already freeze report/layout/notes and source evidence. Preserve
  that workflow and the Working-copy/checkout/permission/token checks in
  [ADR-021](../decisions/ADR-021-drawing-bom-tables.md),
  [ADR-022](../decisions/ADR-022-shared-bom-reports.md) and
  [ADR-028](../decisions/ADR-028-drawing-bom-sort-order.md).
- Current direct row keys include component revision and position; indented keys
  include the ancestor/position path; flattened keys use exact component revision.
  EBOM replacement deletes/recreates database line UUIDs. None of the mutable
  position-based keys or recreated UUIDs alone provides durable identity across
  arbitrary renumbering and BOM edits. Inspect `drawing_bom.row_key`,
  `application/bom_reports.py` and `BOMService.replace_bom` before choosing a key.
- The BOM-entry link and the leader's physical geometry attachment are separate
  problems. A projected view can contain multiple or repeated components; a
  drawing click/source view does not alone establish an unambiguous BOM identity.

## Proposed first increment

1. Select an existing balloon, choose its target table and confirm the intended
   entry using item number, revision, description and position. Reuse native
   balloons and the existing SVG table rather than replacing their renderers.
2. Store an explicit relationship to the table snapshot and entry identity,
   independent of visual row index or literal balloon text. Evaluate a native
   binding object/property exposed through an expression. Resolve rows from
   frozen report data; do not create a competing CAD-derived engineering BOM.
3. Update table data and linked balloon numbers together during an explicit,
   reviewed drawing update, preserving leader placement and style. Missing,
   removed, changed-revision or ambiguous targets need reconciliation; never
   silently bind to whichever entry occupies the old row. A conservative first
   increment can require explicit reconciliation when stable identity is unknown.
4. Validate save/reopen, undo, sorting, language changes, duplicate occurrences,
   revision replacement, orphan links, multiple tables, legacy drawings and PDF
   output. Preserve existing user documents, edits and authenticated sessions;
   use disposable native fixtures for mutations.

Start with Direct BOM support if that keeps the first increment unambiguous.
Indented rows require full occurrence context; Flattened can map many occurrences
to one exact-revision entry. Define these semantics before offering those modes.
Automatic balloon placement, automatic component recognition from projected
geometry, and robust geometry reattachment remain later work.

## Open decisions before implementation

- Persistent entry/occurrence identity and how it survives EBOM replacement,
  renumbering, duplicate/split lines and revision changes. Decide whether the
  initial scope needs backend identity changes or explicit reconciliation only.
- Numbering policy: shared EBOM Position was the research recommendation for the
  first increment, but the user has not accepted it as the final policy. Neither
  automatic EBOM renumbering nor a separate drawing Row/reference column is
  approved. The user wants EBOM/drawing equivalence and raised sequential
  numbering after sorting; keep that question open until links are designed.
- Adoption of existing balloons, target-table scope, unresolved-link presentation
  and validation before PDF publication. Never automatically rewrite existing
  balloons, frozen tables or published PDFs during upgrade/reopen.

No feature code, schema, runtime installation or production drawing was changed
by this research. Continue from the live checkout and verify current document,
session and checkout state before native work.
