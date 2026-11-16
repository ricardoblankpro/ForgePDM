# Prototype provenance

The project began with six FreeCAD macros, a session module and an HTML PDM
specification in `references/legacy`. They informed workflows rather than serving
as backend runtime modules. The repository cleanup removed their inactive copies
after verifying no runtime, test or build dependency used them.

Their unchanged original contents remain in
[commit 3b764ab](https://github.com/ricardoblankpro/ForgePDM/tree/3b764ab8584d06f5df53a729d4b10327fddd579b/references/legacy):

- `PDM_BOM.FCMacro`
- `PDM_Login.FCMacro`
- `PDM_NewItem.FCMacro`
- `PDM_SearchRetrieval.FCMacro`
- `PDM_UpdateRelationships.FCMacro`
- `PDM_UpdateVolume.FCMacro`
- `PDM_Session.py`
- `FreeCAD PDM System.html`

Useful requirements included permanent numbers, revisions after release,
exclusive editing, BOM quantities, project organization and where-used. Direct
JSON state, hardcoded data roots, label-derived identity and non-atomic writes
were replaced by authenticated backend transactions and exact UUID/file pins.
See [the early assessment](guides/architecture.md) and [ADR-001](../decisions/ADR-001-architecture.md).
Original prototype removal does not remove migrations, compatibility APIs,
workspace formats or regression tests for supported installations.
