# ADR-013: Simple material and assembly descriptions

Status: accepted, 2026-11-07. Supersedes the normal user workflow in ADR-012.

The user needs a raw-stock description on P parts and free text on A assemblies,
shown in one tree column and suitable for future TechDraw BOM tables. Mandatory
physical specifications and manufacturing-input review were unnecessarily complex.

Keep permanent M identities, shared-library ownership and existing revision rules.
Require only material description text. A P revision stores one selected M revision
and a frozen description; an A revision stores free text. Empty assignments/text
are permitted on engineering revisions. Existing Released revisions are immutable.
Do not infer consumption or quantities from material selection.

Use an additive revision_descriptions table and native dataset evidence. The
server validates owned checkout, editable lifecycle, M-only references and
concurrency. Native publication commits description evidence alongside the CAD
file; file-hash replay covers the complete metadata. New revisions copy the
assignment/text. M catalog edits do not rewrite assigned engineering descriptions.

Add a read-only Description column to the existing native-tree integration.
Resolve linked rows through exact source revision identities, preserve original
labels/status and keep CAD/Qt operations on the GUI thread. Display local pending
changes without persisting tree-only presentation into CAD.

Remove advanced manufacturing forms from the normal web/addon workflow while
retaining their records and existing API contracts. Migration 14 seeds M text
only; it does not assign P/A descriptions or destroy old specifications/BOMs.
FreeCAD physical material cards remain optional. TechDraw table generation is
explicitly deferred; it must read saved engineering description data.
