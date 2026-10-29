# ForgePDM FreeCAD Addon

- Follow the root instructions and accepted ADRs. Keep plans in docs/.
- Use the official Addon Template, Academy, Manifest Schema and Addon Reports
  as references; document upstream versions and compatibility adaptations.
- Keep source in this monorepo and build a standalone addon distribution.
- Use freecad.forgepdm with modern initialization. Preserve command IDs,
  document metadata fields and versioned backend API contracts.
- Keep manifest, Python version metadata and installed resource paths aligned.
- Do not import the backend or access its database or internal file storage.
  The server remains authoritative for PDM rules and authorization.
- Keep tokens in memory and credentials out of logs.
- Avoid network work at startup. Future network workers must keep FreeCAD
  document and widget operations on the GUI thread.
- Do not silently overwrite working files or substitute latest revisions.
- Test packaging, imports and modified behavior. Distinguish mocked tests
  from actual FreeCAD execution and record the runtime versions used.
- Check licenses before copying code or assets. Do not publish or create an
  external repository without explicit authorization.
