# Item description languages

ForgePDM keeps one item and its engineering revisions across languages. English
(`en`) and Brazilian Portuguese (`pt-BR`) are supported initially. This feature
translates item text; interface labels remain in their existing language.

## Create and display

FreeCAD asks for the source language during new-item, Fasteners and raw-material
registration. The web raw-material form has a Source language selector. The
original revision description remains the canonical engineering text; legacy item names and summaries remain available as history.
Older clients can continue creating items without a language.

Choose **English descriptions** or **Descrições em português** in the FreeCAD
browser, or **Description language** in the web catalog. Approved translations
appear where available; otherwise ForgePDM shows the original text. FreeCAD also
offers **Original descriptions** and remembers the choice per server/account.
The choice applies to subsequent BOM reports and drawing-table generation.
It never changes native `PDMDescription` properties, geometry or server BOM lines.
Search matches original text and approved translations, regardless of the display
language, ignoring case and accents. Drafts are excluded.

## Add and review translations

Open an item/revision and choose **Translations…** in the FreeCAD browser or the
**Translations** tab on the web. Each revision has one description to translate;
historical item text remains read-only.

The web tab compares **Original description** with a clearly named translation
editor. For a confirmed English original it offers Portuguese, and vice versa.
This target is independent of the catalog's **Description language** setting.
When the original language is unknown, choose **Translate into** in the editor.
The comparison stacks vertically when the detail pane is narrow.

1. Check the original text and its language. Legacy records use `und`
   (unconfirmed). The web tab shows a prompt and opens **Original language
   settings** under **Source details & translation history**. Choose the original
   language and **Confirm original language** before approval. For a known source,
   **Correct original language** is available in the same details. This labels the
   existing text; it does not translate it or promote a translation to the original.
2. Enter text and **Save draft**. **Unsaved changes** means the text is only in
   this browser session; **Draft saved** means it is stored for review. In the web
   tab, **Generate from specification** appears for a supported structured standard
   part. Generation uses local terminology, preserves standard identifiers,
   dimensions and grades, and shows warnings for unknown terms beside the draft.
   **Use material translation** appears for a P item only when its exact pinned M
   revision has a matching, accessible reviewed description in that language.
   Both assistance actions save a draft, which still needs review and approval.
   In FreeCAD the corresponding assistance action is named **Generate proposal**.
3. Review/edit the draft, save it, then **Approve translation** on the web
   (**Approve** in FreeCAD). Only saved, unchanged drafts can be approved.
   **Approved** text is available for display. Editors/owners and administrators
   may approve their own drafts; viewers can inspect but cannot change translations.

The web editor retains unsaved text when navigating between tabs, items and
languages in the same session. **Discard changes** restores the last saved text;
signing out clears unsaved buffers. Leaving or refreshing the page warns if text
is unsaved. A concurrent change keeps your text and offers **Reload latest state**;
compare with the latest original, then explicitly save again. The item header and
catalog update after approval without leaving the web translation editor.

Approval does not require a CAD checkout or create an engineering revision,
including when translating a Released revision. Existing original-description
editing still requires its normal Working/checkout permissions. Each revision description has its own source language and review history. Legacy item text retains its original history.

A missing translation falls back to the original. A new draft keeps the previous
approved version visible. Editing original text or correcting its source language
marks existing active translations **needs_review**, immediately restoring the
original fallback. Save a new reviewed draft against the current source before
approving again. Concurrent changes require reloading rather than overwriting.
Refresh/reopen other open presentations after approval to update them.

## Engineering snapshots

Material descriptions remain independent snapshots of an exact M revision.
Later M edits/translations never automatically rewrite P descriptions. Unchanged
text and its reviewed translations can be copied when explicitly creating the
next engineering revision; subsequent edits are independent.

New localized TechDraw tables embed language, displayed strings and source/
translation provenance (saved format 3). Previously saved format-1/2 tables remain
readable. Reopening, recomputing or switching language never updates a saved
table or published PDF. Updating a table remains an explicit Working-copy action;
released document bytes and file/revision pins remain stable.

There is no automatic language detection, bulk legacy classification, AI service,
external translation dependency or automatic approval. More languages/providers
can be added through the central backend service after terminology and review
policy are defined.

## Fasteners proposal coverage

The local pt-BR vocabulary covers every type/family in the shared standard map
and the current controlled material/finish choices. Family names remain general:
an autotravante nut does not imply a nylon insert, and a flange does not imply
serrations. Standard-specific details may need manual review. Engineering codes,
dimensions and mechanical classes keep their canonical values; known material
identifiers such as PA66 and INCONEL 718 remain identifiers.

Unknown material/finish terms retain their original spelling with a warning in
the draft provenance. Missing purchasing properties are explicitly unspecified;
an unknown standard requires manual translation. Vocabulary updates affect new
proposals only. Existing approved text remains visible until another draft is
reviewed and explicitly approved.
