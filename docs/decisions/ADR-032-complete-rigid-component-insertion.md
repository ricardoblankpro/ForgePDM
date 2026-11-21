# ADR-032: Complete rigid component insertion

Status: accepted for addon 0.27.0.

## Context

Fasteners Workbench objects can live outside a native Assembly container. Native
Insert Component links the container and omits these objects, although ForgePDM's
source-document BOM includes them. Moving source fasteners into the container is
not part of the insertion workflow.

## Decision

The browser offers Insert into Assembly for an exact uploaded P or A snapshot.
A destination-owned App::Part representation contains whole-object App::Link
members to the source Assembly and its external supported fasteners. A native
App::Link occurrence inside the destination Assembly links this representation.
The source document remains intact. Subassemblies are rigid; no shape copies or
custom geometry proxies are introduced. Each occurrence owns its representation.

Version-1 ForgePDMRepresentation metadata records ordered member names. Validation
reconstructs expected membership from the source, rejecting missing, extra or
changed member targets. Shared resolution supplies source identity to BOM, tree
labels and balloons. Internal member links are CAD dependencies, not additional
parent BOM occurrences. Source BOMs continue to own their fasteners and mass.

Existing exact-file workspace retrieval and external-reference contracts carry
all members. There is no new HTTP API or schema. Older addons cannot extract this
representation's BOM because its internal target lacks an external identity;
upgrade before editing these documents. Native offline geometry remains readable.

Snapshot/revision replacement rebuilds the representation inside the existing
replacement transaction. Occurrence placement is retained; existing joint checks
reject unresolved geometry and roll back the change. Native closure tests must
run in a separate process/profile/display, never in the user's working session.

## Consequences

Insertion requires a managed Working destination and an owned live checkout.
Save/upload and BOM review remain separate explicit steps. Flexible subassemblies,
arrays and arbitrary source proxies remain unsupported. Source Fasteners support
must be installed; unsupported membership fails instead of silently dropping parts.
