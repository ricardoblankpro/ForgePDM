# ADR-015: Supplier reference mass for Standard Parts

Accepted, 2026-11-07.

Keep existing S identities, purchasing specifications and revision workflows.
Add supplier reference mass as an explicit revision record, separate from
CAD-calculated P mass. No M item is required for a purchased fastener. Assembly
mass aggregation is a later feature.

Attempt optional enrichment after an API-created structured S fastener commits,
and when FreeCAD explicitly selects/reassociates a catalog fastener. Reuse an
existing reference without network access. Saving a new reference requires an
owned Working checkout and library edit permission. Released records remain
immutable; new revisions copy the reference. Readers can reuse saved references.
Network/provider failure must not make successful Item creation appear to fail.

Use an exact normalized purchasing-specification hash, explicit original mass,
unit and piece count, supplier/article/HTTPS source and retrieval timestamp.
Normalize to kg per piece with Decimal. Record the product response SHA256 for
live reads. Do not infer packaging mass, unknown material/finish, unsupported
pitch/geometry or automatic DIN/ISO substitutions. The supplier page must list
the requested standard and exact product attributes. CSV reference feeds match
the full specification hash. An ambiguous duplicate feed is rejected atomically.

Fabory has no verified public search API. Its robots policy disallows search
and -sku product paths. Do not crawl those routes. The initial adapter reads only
specific dimension-qualified public product URLs for an explicit family list,
checks robots first, disables redirects and rejects incomplete/conflicting
product evidence. Requests use timeouts and response-size bounds. A one-hour
per-revision cooldown limits repeated unsuccessful requests; reserve attempts in
a transaction, perform network I/O outside locks, then revalidate checkout and
specification before saving. There is no automated bulk crawl or bundled supplier
database. Extend supported families only with verified pages and tests.

Allow administrator-imported supplier CSV as a stable/offline reference feed.
This is local catalog enrichment, not purchasing, stock or supplier management.
A feed update affects future adoptions only; it never rewrites an existing S
revision reference. Do not advertise a full catalog or guaranteed source access.

Migration 16 adds revision_reference_mass, supplier_mass_feed and
supplier_mass_attempts. Existing Items/revisions/BOM pins are unchanged. Native
FreeCAD association metadata remains unchanged: the S revision pin resolves the
reference mass. No local shape or default density is substituted for a missing
supplier result. ERPNext synchronization is outside this increment.
