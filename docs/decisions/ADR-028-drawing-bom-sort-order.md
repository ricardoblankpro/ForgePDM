# ADR-028 — Frozen drawing BOM sort order

Status: accepted, 2026-11-18. Extends ADR-021/022 drawing presentation; engineering
BOM positions, quantities, revision pins and update permissions remain unchanged.

New TechDraw BOM layouts default to ascending item number. The drawing editor
also offers stored BOM order, BOM position, displayed description, quantity per
root and unit/extended mass, with ascending/descending order for sort fields.
Text uses deterministic accent/case-insensitive natural comparison; numeric
quantities and masses use Decimal values, with missing values last in either
direction. Equal values retain the report's original order. Indented reports
sort only siblings and move complete subtrees with their parent.

Sorting is a pure presentation over the original frozen report. Preview and SVG
use the same row ordering; source rows, evidence tokens, positions and custom-text
identities never change. Notes remain keyed to their original occurrence/revision,
not their visual row index. Presets and embedded layouts retain sort settings.

A layout without sort settings preserves the stored report order. Existing
format-1/2/3 tables remain readable and are never rewritten on upgrade/reopen.
Explicitly sorted tables use PDMTableData format 4, which requires an explicit
sort field and direction, and retains language/provenance when present. This
makes older addons reject updates they cannot preserve; their native embedded
SVG remains viewable offline. An explicit update using stored BOM order retains
the prior format selection (1/2/3). No backend or database schema change is needed.

The normal owned Working-copy checkout, permission, report-token revalidation,
placement validation and undo transaction still gate explicit insertion/update.
Sorting does not save, upload, check in or modify previously published PDFs.
