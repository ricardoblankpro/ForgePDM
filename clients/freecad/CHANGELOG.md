# Changelog

## 0.1.0 — development preview

- Migrate existing commands to the modern `freecad.forgepdm` namespace.
- Add standalone ZIP packaging, offline manifest checks and original SVG icon.
- Preserve command IDs, document metadata and backend API requests.
- Prompt for a writable copy when uploading a read-only document, such as a
  bundled FreeCAD example inside an AppImage; report save failures with the path.
- Explain project IDs versus project numbers, reject malformed IDs before item
  creation, and display readable API validation messages instead of raw errors.
- Actual FreeCAD GUI validation and public distribution approval remain pending.
