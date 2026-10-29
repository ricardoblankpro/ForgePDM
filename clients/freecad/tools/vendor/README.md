# Official manifest schema snapshot

`manifest.xsd` bundles the declarations from FreeCAD/Addon-Manifest-Schema,
release `v1.0`, commit `25158f37049e42ae2aa297f8ce2350e075a93031` (manifest format 1).
See `provenance.json` for the checksum and derivation. Includes were expanded
once in traversal order; comments and documentation annotations were removed.
Upstream validation declarations are unchanged. No AGPL-licensed scripts were
copied. The schema is licensed under the included `LICENSE_SCHEMA` (Unlicense).

Sources:

- https://github.com/FreeCAD/Addon-Manifest-Schema/tree/25158f37049e42ae2aa297f8ce2350e075a93031
- https://github.com/FreeCAD/Addon-Template
- https://freecad.github.io/Addon-Academy/Topics/Structuring/Manifest/
- https://github.com/FreeCAD/Addon-Reports

## Explicit compatibility bridge

The template and Academy specify `https://wiki.freecad.org/Package_Metadata`
and manifest format 1. The current Stable schema requires format 2 and targets
`HTTPS://Addons.FreeCAD.Org/Manifest`, so it cannot validate the official template.
The published v1.0 schema instead describes format 1 without a target namespace.

`template-namespace.xsd` uses standard XSD chameleon inclusion to bind the pinned
v1.0 declarations to the template namespace. The manifest is never stripped of
its namespace or rewritten for validation. No upstream field constraints are
changed. This namespace binding is explicit in the check output; it is not a
claim of validation against the format-2 Stable schema or execution of FreeCAD.

The v1.0 Workbench declaration includes name, classname, subdirectory and icon,
so the manifest supplies all four. Additional local checks enforce required field
counts, identity, version agreement, resource existence and the implicit namespace
boundary because the schema's repeating choice does not enforce all documented
required fields.

This snapshot is development tooling and is excluded from the installed addon.
