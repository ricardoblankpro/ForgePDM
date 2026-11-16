# Domain model and invariants

The database owns identity, lifecycle, relationships and audit metadata; the
separate blob store owns immutable bytes. Names, filenames and FreeCAD labels
are presentation, never lookup keys for engineering identity.

| Entity | Current responsibility |
|---|---|
| Item | Permanent number, part/assembly kind, master metadata and current revision pointer |
| ItemRevision | Exact item revision UUID, sequence/label, lifecycle, change note and attribution |
| Dataset | Named/typed revision attachment; multiple native/derived uploads can exist on one revision |
| File | Immutable hash/size/type/original-name/storage-key metadata; bytes may deduplicate independently |
| BOMLine | Parent assembly revision → exact component revision, positive Decimal quantity and stored position |
| Project | Independent organization/access context; reused Items can belong to multiple projects |
| User | Enabled account, global role and project/library memberships |
| Checkout | Exclusive time-bounded revision lease with UUID/version and owner |
| LifecycleState | Working, Released or Obsolete with audited transitions |

## Engineering rules

- Independent permanent P/A/S/M series use a prefix and six digits. P is a
  manufactured/custom part, A an assembly, S a standard/purchased part and M a
  raw material. S/M are part-kind Items in a shared library.
- New items start Working at revision A with an eight-hour owned checkout. Labels
  follow A…Z, AA… from the sequence; configurable label policies are not implemented.
- Edits need access, Working lifecycle and a live owned lease. Released content
  is immutable. Working → Released → Obsolete is the lifecycle; changes after
  release use an explicit next Working revision with a required change note.
- Check-in notes are optional and preserve the existing note when omitted.
  Native check-in atomically publishes exact bytes/evidence/manifest and releases
  checkout; ordinary attachment upload keeps the lease. Durable retries recover
  the original intent rather than republishing newer edits.
- Every engineering BOM line pins a child revision. Cycles and obsolete new
  components are rejected. Working components may be used during development;
  release requires all direct components Released. Next assembly revisions copy
  the previous stored BOM. Report views never rewrite those pins or positions.
- CAD manifests bind exact revision/dataset/file/object dependencies, independently
  of BOM quantities. Upload/check-in never implicitly synchronizes the BOM.
- Project membership is independent of BOM use and item ownership. Removing a
  membership does not delete an Item, revisions or released evidence.

## Descriptions and evidence

P descriptions pin an M revision/text, A uses free text and M stores catalog
text. Optional physical links freeze native UUID/name/density/attribution; part
mass evidence belongs to exact native datasets. Later M changes do not rewrite
assigned parts. Changed engineering assignments invalidate incompatible mass.

S specifications encode exact geometry/material/class/finish. Saved mass is
revision-bound supplier, CAD estimate or manual evidence, with source priority
and optimistic concurrency. Missing/estimated values retain their meaning; no
unknown contribution becomes a complete zero total. The shared assembly report
multiplies quantities through exact paths and summarizes leaves once.

Advanced material-input/requirements records remain available through
compatibility APIs, although the normal UI uses simple descriptions. Database
migrations and old native/manifest formats remain upgrade/retrieval contracts.
Do not delete them as prototype leftovers. See [compatibility APIs](api.md) and
[accepted decisions](../decisions/README.md).
