# ADR-009 — Explicit source-pinned drawing PDF publications

Status: accepted, 2026-11-03.

TechDraw pages remain part of their native ItemRevision. Publish a separate,
immutable set of derived PDF datasets rather than introduce drawing items or
server-side FreeCAD. One PDF per native page supports simple selection and
retrieval without a PDF-merging dependency. The source relation uses exact
native dataset/file/hash identities, including the verified configuration's
pinned children. It is not a server-side assertion of geometric equivalence.

The client renders isolated copies on FreeCAD's GUI thread. A temporary modal
progress guard prevents editing those copies before they are discarded; original
engineering documents are never saved by publication. Durable frozen bytes and
an actor-scoped operation ID make retry independent of later local edits.

An additive schema and API keep native check-in independent. Require edit access,
Working state and the exact live owned checkout before staging and in the final
serialized metadata transaction. Publish the whole page set and its audit event
together; do not release or renew the lease. Promoted immutable blobs may remain
unreferenced on rollback under the existing storage design.

Exact source identity means later native uploads/check-ins make earlier PDFs
historical even if native bytes match. Do not silently relink or regenerate them.
Automatic native-check-in inclusion needs a later combined intent/transaction
increment; changing checkout or release rules to hide this distinction is outside
this increment.

The web app fetches authorized PDF bytes with bearer headers and displays a
short-lived Blob URL in an iframe, using the browser's native PDF support. This
avoids third-party runtime viewers and credentials in URLs. Revoke previews on
navigation/logout/expiry and provide explicit download fallback. CSP permits only
Blob frames while retaining object-src none. The first increment validates PDF
signature/end marker, size and hashes, not arbitrary PDF content semantics.
