# Personal component catalog — planning entry point

This historical implementation sequence is the [simplified standard parts implementation plan](../ForgePDM_Standard_Parts_Implementation_Plan.md),
reformulated on 2026-11-05 around the immediate Fasteners Workbench BOM problem.

Use that document as the authoritative sequence: reproduce the CAD failure, add
ordinary S-numbered items, deliver manual fastener association and reviewed BOM
counting for one supported case, then validate purchased-model reuse through existing
managed links. Geometry matching and explicit full-specification selection were delivered in
the subsequent Standard Parts increments; broader supplier management remains
deferred. This replaces the earlier three-increment catalog proposal.

Status: implemented in addon 0.7.0 and migrations 10–11. See [current usage and validation](standard-parts.md).

Current client: **0.11.0**, schema **16**. Shared S/M library ownership, controlled
Fasteners registration and optional revision-bound supplier reference mass have
since been delivered. Use [Standard Parts](standard-parts.md),
[materials](material-management.md) and [reference mass](supplier-reference-mass.md)
for current behavior rather than this historical sequence.
