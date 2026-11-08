# ForgePDM Domain Model

The relational database is the authority for identity, relationships, lifecycle, and audit metadata. CAD bytes are immutable files in the separate blob store. Database IDs are opaque internal identifiers; human-readable item numbers remain stable business identifiers and are never reused.

## Core entities

| Entity | Responsibility and key relationships |
|---|---|
| **Item** | Stable product identity: unique item number, type (part/assembly), name/description, creation time, and current revision pointer. Belongs to zero or more Projects through project membership; one Item may be reused across projects. |
| **ItemRevision** | Immutable revision identity and sequence/label, parent Item, lifecycle state, change note, creator, timestamps, and optional predecessor. Working content may be updated only under checkout; released revision data is immutable. The legacy A→B→… scheme is a configurable initial label policy, not an identity key. |
| **Dataset** | A logical named/typed attachment to an ItemRevision (for example native CAD, drawing, STEP, or PDF). A revision can have multiple datasets of the same or different types. |
| **File** | Immutable stored blob metadata: content hash, byte size, media type, original filename, and storage key. A Dataset references one or more Files to allow packaged or derived deliverables. Hash uniqueness can deduplicate identical bytes without conflating dataset meaning. |
| **BOMLine** | Occurrence from a parent assembly ItemRevision to a child ItemRevision, with positive quantity and position. The line references an explicit child revision so the assembly structure is reproducible; cycles are rejected. |
| **Project** | Named workspace/context with active/archive status and timestamps. Membership links Items to Projects; project organization does not own or delete a reused Item. |
| **User** | Stable account identity, display name, credential/authentication reference, enabled flag, and role/permissions. Actor references on revisions, checkout, and audit events preserve attribution. |
| **Checkout** | Time-bounded exclusive editing claim on one ItemRevision, owned by one User, with created/expiry timestamps and optimistic version. Check-in or authorized release closes it; stale-lock recovery is auditable. |
| **LifecycleState** | Controlled state definition (initially Working, Released, Obsolete) plus allowed transitions/policies. Each ItemRevision points to its current state; transitions are audited. Released revisions cannot be edited; modification creates a new revision. |

## Important rules

- Item numbering is allocated transactionally and uniquely: P manufactured/custom parts, A assemblies, S standard/purchased parts, M raw materials. Codes are permanent seven-character identifiers (prefix + six digits). S/M are part-kind Items in the shared library, not duplicate purchasing identities.
- New Items start with revision A in Working. Saving working content does not create a new revision. Revision advances after a released revision is revised; the prior released revision and its files remain immutable.
- Dataset/File relationships are revision-scoped; replacing a file creates a new association/version rather than overwriting bytes.
- Each uploaded attachment currently creates one Dataset and one File association. Identical file bytes can share the same hash-derived storage object while retaining distinct File metadata and original filenames.
- Checkout targets a revision, while lifecycle controls whether it may be checked out. A released/obsolete revision is read-only; work proceeds on a new Working revision.
- Creating an Item or a new revision automatically creates an eight-hour checkout for its creator. File attachment requires that active lease; check-in records the change note and releases the lease. Expired leases are reclaimable, and administrator override requires an audited reason.
- BOMLine stores an explicit child revision, quantity, and order. This is a deliberate historical snapshot rule; “latest revision” views can be added as queries, not silently substituted into stored BOMs.
- An assembly revision can be released only after all direct component revisions in its BOM are Released. Creating a new assembly revision copies its prior BOM lines so the new revision starts from the released structure.
- Project membership and BOM structure are separate relations. Removing an item from a project does not delete the Item or its revision history.

## Lifecycle and checkout flow

```text
Create Item → Working revision A → checkout / edit / check-in
                                  → release
                                  → create Working revision B → ...
Released → Obsolete
```

Checkout is an exclusive lease, not authentication. The API authenticates bearer sessions and checks global role or project membership on item operations. Project roles are owner, editor, and viewer; editors/owners may create project items and viewers may read. Recovery/administrative override records actor, reason, and timestamp. MVP lifecycle transitions are Working → Released → Obsolete; moving from Released back to work requires creating a new revision. A configurable approval workflow is out of scope.

## Current extensions and deferred questions

The implementation uses global independent series counters, many-to-many project
membership, revision-scoped datasets and positive decimal EBOM quantities.
Working BOMs may refer to usable Working components; release requires direct
components to be Released. Independent dataset lifecycle, deletion/retention,
effectivity and production inventory semantics remain deferred.

Schema 16 also contains these engineering extensions:

| Record | Responsibility |
|---|---|
| Standard specification | Existing S Item geometry/material/class/finish identity and exact catalog matching; assemblies pin S revisions. |
| Revision description | Frozen selected M revision/text on P, free text on A, catalog text on M. Changes need owned Working checkout and concurrency tokens. |
| Physical material link | Optional M-revision source UUID/name/density/attribution snapshot. P revisions freeze selected physical snapshots separately; M edits do not rewrite them. |
| Dataset description/mass evidence | Immutable native description, final-solid volume/material evidence and computed kg tied to exact CAD dataset/file hash. CAD measures volume; backend validates the snapshot and arithmetic. |
| S mass | Supplier reference, CAD volume/reference-density estimate or explicit manual grams per piece. Optimistic tokens protect fallback edits; audit retains source changes. Saved on an owned Working S revision, copied forward, immutable after release. |
| Supplier feed/attempt | Administrator-imported exact-specification CSV references and bounded lookup cooldowns; neither is an inventory or purchasing ledger. |

Advanced manufacturing inputs and requirements from migration 13 remain stored
and available through compatibility APIs, but are hidden from the current simple
UI (ADR-013). No stock consumption is inferred from a material description.
Assembly mass totals, TechDraw BOM generation and ERPNext synchronization remain
future work. See [materials](material-management.md),
[reference mass](supplier-reference-mass.md) and ADR-012 through ADR-015.

## CAD reference manifests (Phase 3)

A native Dataset may have one immutable manifest binding its source File to CAD
occurrences: object/property → target ItemRevision, Dataset, File and object.
These technical references are distinct from BOMLine and contain no engineering
quantity or automatic BOM synchronization. Exact dataset/file pinning prevents
historical CAD retrieval from substituting a later upload of the same revision.
The server enforces authorization, membership, checkout and cycle rules; the
client adapter verifies the native document links. See ADR-004 for profile limits.
