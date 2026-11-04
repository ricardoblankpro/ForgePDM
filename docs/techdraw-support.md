# Embedded TechDraw pages — addon 0.6.5

## Implementation

1. Support native `TechDraw::DrawSVGTemplate.Template` specifically when the same
   object has an `App::PropertyFileIncluded` PageResult pointing to a real, bounded,
   self-contained SVG member in the FCStd archive. Keep rejecting other external
   File/Path properties and unsupported cross-document drawing references.
2. Validate embedded SVG structure and resource references; reject missing files,
   unsafe member names, entity/DTD declarations, scripts and external SVG/image/CSS
   resources. Permit local fragment references and embedded PNG/JPEG data images.
   Never fetch or depend on the original Template path on the uploading machine.
3. Preserve the uploaded FCStd bytes and existing reconstruction behavior. FreeCAD
   restores PageResult from the archive; do not reassign Template during retrieval,
   which would replace the template and potentially reset editable title fields.
4. Treat TechDraw documentation objects as non-BOM objects, including pages in a
   native assembly group. Preserve existing component adapter restrictions.
   Wait for native Qt projection/face jobs and queued GUI results to settle before
   saving managed or reconstructed drawing documents. This bounded GUI-event wait
   preserves GUI responsiveness; unresolved computation rejects the save/update
   rather than recording an unfinished snapshot. Non-TechDraw documents are unaffected.
5. Clarify local validation failures: no transfer for the failed validation, while
   still reporting earlier successful server changes and retaining transport-loss
   warnings for requests that actually reached the server.
6. Test malformed/missing/external resources and archive rewriting, then real part
   and native-assembly upload/check-in/retrieval with the original SVG unavailable.
   Verify editable title fields, views, dimensions, clean restored documents and
   unchanged exact component pins. Use disposable DB/storage/CAD fixtures only.

Pages share the model's revision, checkout and native snapshot. Separate drawing
items/revisions, PDF publication, externally sourced drawing views and other file
asset adapters remain outside this increment.

## Usage and supported boundaries

Use Create/Upload and Check In normally after adding a TechDraw page. On save,
FreeCAD embeds the selected SVG template in `PageResult`. ForgePDM verifies that
embedded member instead of requiring the original `Template` path. Download opens
the page from the embedded copy; the old path can remain visible in its property.
Do not change Template merely to repair that historical path: FreeCAD may reset
editable fields when replacing templates. To intentionally change a template,
choose its new file in an owned working copy and check in normally.

Templates must contain valid standalone SVG without external images/stylesheets,
DTD/entities or active content. Local SVG fragment references and embedded PNG/JPEG
data images are supported. Other external file/path assets and cross-document
drawing-view sources still require dedicated adapters. Native text rendering also
depends on fonts available in FreeCAD/the operating system.

Model revision, checkout and exact component pin rules remain unchanged. Pages are
documentation, including when grouped inside a native Assembly; views do not add
their source geometry to BOM quantities. No automatic PDF publication or drawing
revision entity is introduced. No backend schema/API changes are required.

## Validation

Automated tests cover embedded template validation, archive-byte preservation,
missing/unsafe/oversized/invalid SVG, external resources and active-content rejection,
internal fragments/embedded images, unaffected external-file guards, assembly BOM
exclusion and precise local-validation error reporting.

Actual FreeCAD 1.1.4/HTTP acceptance passed 43 checks using disposable DB/storage and
CAD workspaces: two-page part, native assembly page, atomic check-in, original SVGs
renamed away, download/reconstruction, edited title re-check-in, 100 mm dimensions,
notes, embedded PNG logos with wrapped Base64 data and SVG rendering, clean retrieved files and exact assembly pins. The tests
assert clean state before native SVG export: FreeCAD's export operation itself can
mark its document modified. Existing user documents, dirty states and saved bytes
were preserved. Evidence: [live report](validation/freecad-techdraw-2026-11-03.json).
