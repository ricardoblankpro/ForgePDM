# ADR-018 — Combined BOM review and display-only mass rounding

Status: accepted and implemented, 2026-11-11.

## Context

The original reviewed replacement workflow required selecting every occurrence,
opening a second review dialog and ticking separate replacement consent. Routine
CAD assemblies incurred repeated clicks. Raw Decimal mass strings also leaked
calculation precision into the native and web presentation.

## Decision

Keep one published BOM window with an expandable tree, mass summary, background
revision notices and asynchronous requests. Combine CAD inclusion and replacement
review in this window. Include every supported engineering candidate by default;
provide optional occurrence checkboxes and one explicit Apply action. Detect exact
revision/position/quantity no-ops. Require additional confirmation for clearing,
reducing/removing components and replacing split lines or custom positions.

This deliberately changes the old opt-in inclusion rule. Server authorization,
owned Working checkout, uploaded snapshot/hash verification, exact revision pins,
GUI document revalidation and optimistic replacement tokens remain unchanged.
There are no automatic writes on view, upload or check-in. Failed writes invalidate
the proposal; unknown outcomes require inspection and never retry automatically.

Display masses with Decimal half-up rounding to three decimals, stripping trailing
zeros. Show positive values below 0.001 in the displayed unit as `<0.001`.
Python uses Decimal; web uses decimal-string/BigInt arithmetic including gram
conversion before rounding. Evidence, backend values and editable inputs remain
unrounded. This is a client presentation change without a schema/API migration.

## Limits and validation

CAD-to-BOM provenance is not persisted, so manual lines and previous exclusions
cannot be identified authoritatively. Always show current/proposed lines and an
explicit warning about inferred defaults. Subassembly BOMs remain independent.
Native property presentation updates through normal recomputation; installation
must not dirty existing CAD documents merely to reformat them.

Automated domain/regression tests and real offscreen Qt tests cover formatting,
combined review, cancellation, exact no-ops, empty replacement confirmation and
stale writes. FreeCAD 1.1.4/Qt 6.8.3 acceptance covers the actual command and live
read-only HTTP plus fake-service Apply. Real Chrome checks presentation with
controlled API responses and description workflows on an isolated backend.
Production synchronization was not exercised.
