# Published TechDraw PDFs

Available with FreeCAD addon 0.6.6 and backend migration 9.

## Use

1. Save and upload the final CAD document. The active document must be a clean,
   uploaded managed working copy of a Working revision with your own checkout.
2. Choose **ForgePDM → Publish Drawing PDFs…**. Select the TechDraw pages and
   confirm the displayed native source and page list.
3. Open the item and revision in the web GUI, select **Drawings**, then choose a
   publication/page and **Preview PDF** or **Download PDF**. Refresh the browser
   after updating the server to load the new tab.

FreeCAD exports one PDF per selected page from isolated verified configuration
copies. Your active engineering documents, selection and checkout remain intact.
The web viewer uses the browser's PDF support; download remains available when
inline viewing is unavailable, including on some mobile browsers.

Publication is separate from native upload/check-in. A later native upload or
check-in creates another source snapshot and can make the PDFs historical, even
if its bytes are identical. The Drawings tab warns when the same revision has a
newer native snapshot. Review and publish again explicitly as needed. A newer
revision has its own Drawings list; existing publications remain readable on their
original revision, including after release. Child-part updates do not rewrite an
assembly's pinned drawing source.

## Recovery and limits

After a timeout or lost response, invoke Publish Drawing PDFs again. The command
queries its actor-scoped operation and retries the exact frozen PDF bundle if
needed; it does not render newer local edits into an old operation. If a checkout
has changed, an explicit choice can retain the pending operation or archive an
uncommitted attempt before reviewing a new one. Frozen files and journals are
retained locally; automatic cache cleanup is deferred. Journals contain no tokens
or passwords.

A publication contains 1–32 pages, at most 25 MiB per PDF and 100 MiB total.
Combined multi-page PDFs, automatic native check-in integration and server-side
CAD rendering are deferred. Source links attest to the client-rendered input;
the server validates byte hashes, PDF signatures and metadata, not CAD geometry
or full PDF syntax. As with existing storage, a failure after promotion can leave
unreferenced immutable blobs; orphan recovery remains a separate hardening task.

## Validation

- 130 backend tests, 295 addon tests and three web model tests passed.
- Live FreeCAD 1.1.4 fixture: 59 checks, including two-page part/assembly PDFs,
  exact pinned sources, lost-response recovery, release/revision history and
  preserved original documents/bytes/selection.
- Real Chrome: 18 drawing checks, including authenticated download, native PDF
  preview, stale sources, publication/page navigation, URL cleanup and mobile
  layout. Existing web/management suites passed 26 and 23 checks respectively.
- Fixtures are disposable; no user engineering drawing was automatically uploaded.
  Evidence is in `docs/validation/drawing-pdfs-*-2026-11-03.json`.

## Implementation and guarantees

1. Add migration 9 for immutable drawing publications and per-page PDF/source
   associations. Keep existing native snapshots, leases, passwords and data intact.
2. Publish a reviewed set atomically through an explicit derived-drawings endpoint.
   Require current edit access, Working revision and exact owned lease ID/version
   at preflight and final transaction. Verify native dataset/file/revision/hash
   membership and each PDF's bytes. No implicit checkout acquisition/release.
3. One operation UUID and durable client journal retain exact exported bytes and
   intent. Actor-scoped replay/status prevent duplicate pages after response loss.
   Transport uses a bounded ZIP of fixed PDF member names, never archive extraction.
4. FreeCAD Publish Drawing PDFs uses a clean uploaded active document and verified
   configuration copy. Review selected pages/source, settle projections and export
   on the GUI thread under a temporary modal progress guard. Discard only owned
   export copies, preserve original documents/selection/dirty states and recheck
   source/lease before upload. HTTP and hashing remain worker operations.
5. Add web Drawings tab with publication/page selection, exact source/timestamps,
   newer-native-snapshot indication, authenticated PDF preview/download and refresh.
   Fetch with bearer headers; use temporary application/pdf Blob URLs, revoke and
   remove previews on navigation/logout/expiry. No tokens in URLs/browser storage.
6. Validate authorization, migration preservation, stale/changed leases, rollback,
   replay, PDF/bundle bounds and real FreeCAD-to-browser workflows against disposable
   fixtures. Inspect desktop/mobile preview and preserve real user engineering data.

Publication is explicit and separate from native upload/check-in. Released revisions
remain read-only. One PDF per TechDraw page; combined PDFs, automatic check-in
integration and server-side FreeCAD rendering are deferred. The source association
records the client's verified rendering input, not a server-side CAD regeneration.
