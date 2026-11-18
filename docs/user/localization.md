# Item description languages

ForgePDM keeps one item and its engineering revisions across languages. English
(`en`) and Brazilian Portuguese (`pt-BR`) are supported initially. This feature
translates item text; interface labels remain in their existing language.

## Create and display

FreeCAD asks for the source language during new-item, Fasteners and raw-material
registration. The web raw-material form has a Source language selector. The
original designation and description remain the canonical engineering text.
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
**Translations** tab on the web. Select the text context (designation, master
summary or revision description) and the target language. In the web editor,
the catalog's Description language is the target language.

1. Check the original text and source language. Legacy records use `und`
   (unconfirmed); choose the original language and **Confirm/correct source
   language** before approval. This labels the existing text; it does not
   translate it or promote a translation to the original.
2. Enter text and **Save draft**, or **Generate proposal** for a supported
   structured standard part. Generation uses a local terminology dictionary,
   preserves standard identifiers/dimensions/grades, and reports unknown terms.
   A P material description can propose a copy of its exact pinned M revision's
   approved translation when the original snapshot still matches.
3. Review/edit the draft, save it, then **Approve**. Only saved drafts can be
   approved. Editors/owners and administrators may approve their own drafts;
   viewers can inspect but cannot change translations.

Approval does not require a CAD checkout or create an engineering revision,
including when translating a Released revision. Existing original-description
editing still requires its normal Working/checkout permissions. Each text
context has its own source language and review history. The designation language
is also recorded as the item's source-language metadata.

A missing translation falls back to the original. A new draft keeps the previous
approved version visible. Editing original text or correcting its source language
marks existing active translations **needs_review**, immediately restoring the
original fallback. Save a new reviewed draft against the current source before
approving again. Concurrent changes require reloading rather than overwriting.
Refresh/reopen the item after approval to update other open presentations.

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
