# Fastener selection options — research for specification-only registration

Status: research inventory; the common/extended registration registry is implemented
in addon 0.7.3. See docs/standard-parts.md for actual supported choices and limits. Research date:
2026-11-05. Scope: broad industrial fastener vocabulary, including ISO metric,
SAE/ASTM and specialist materials. It is not a certified exhaustive list of every
alloy, commercial coating or permitted product/size/material/class combination.

## Recommended form

Read standard/type/dimensions from Fasteners Workbench. Ask only for purchasing
specification selections, plus project when registration needs one. Generate the
catalog name and description from the resulting specification; remove duplicate
free-text name/description prompts from the ordinary fastener-registration flow.

Use searchable dependent selectors: material (with group/alloy), mechanical class
(with its standard), and finish (with its process/specification). Offer Common and
Extended views. Retain Unknown separately from Not applicable and Plain/uncoated.
New controlled list entries belong in catalog administration, not arbitrary typing
on each registration. These are proposed product decisions, not existing behavior.

## Material options

| Family | Proposed selectable values / subtypes |
| --- | --- |
| Steel | Steel, alloy unspecified; carbon steel; alloy steel; spring steel |
| Austenitic stainless | A1; A2; A3; A4; A5; A8; documented low-carbon variants where specified |
| Other stainless | Ferritic F1; martensitic C1/C3/C4; duplex D2/D4/D6/D8 |
| Supplier-designated stainless | 18-8; 304; 305; 316; 316L; 410, retained under their own designation system |
| Copper and copper alloys | Copper; brass; phosphor bronze; silicon bronze; aluminium bronze; nickel silver; copper-nickel-silicon |
| Aluminium | Aluminium, alloy unspecified; exact alloy/temper entries when specified by supplier |
| Titanium | Titanium Grade 2; Titanium Grade 5 (Ti-6Al-4V); other documented supplier grades in Extended |
| Nickel alloys | Monel; Inconel; Hastelloy; Nimonic; require exact alloy/product specification for a complete specialist identity |
| Polymers | PA6; PA66; POM; PP; PE-HD; PE-LD; PEEK; PTFE; PFA; PVDF; specialist PAI/PI grades in Extended |
| Composite products | Preserve component materials separately when needed, e.g. a steel nut with a polymer insert; do not call the complete nut “nylon” |

Sources for the vocabulary: [Accu material families](https://www.accu.co.uk/c/22-materials),
[Bolt Depot material descriptions](https://boltdepot.com/fastener-information/materials-and-grades/Materials),
[Bossard various-materials guide](https://www.bossard.com/global-en/knowledge-hub/resources/technical-information/fasteners-of-various-materials/),
[Bossard stainless overview](https://www.bossard.com/global-en/knowledge-hub/resources/technical-information/stainless-steel-fasteners/),
[Accu titanium grades](https://www.accu.co.uk/p/46-titanium), and
[UC Components material overview](https://uccomponents.com/considerations-for-selecting-the-proper-fastener-materials-for-your-application/).

The Bossard [2025 various-materials tables](https://assets.eu.ctfassets.net/0vp0u5uh75zd/2mI2x8t6g9RvmQN8tOJaQu/59da75eef27d30238c37e5bd2e331f39/039_044_Fasteners_various_materials_Fastening_EN_01_2025.pdf)
provide extended supplier vocabulary, for example aluminium 5019/6082/6056/6060/
6013/2017/7050/7075 with distinct tempers; CuZn37, CuZn39Pb3, CuSn6 and
CuAl10Ni5Fe4; and specific Hastelloy/Inconel/Monel/Nimonic alloys. These examples
must not be silently reduced to one generic alloy, nor enabled for every geometry.

ISO stainless groups and AISI/EN material numbers are not interchangeable one-to-one
catalog identities. Likewise, a strength class does not necessarily identify the
exact steel chemistry. “Steel, alloy unspecified” is useful when the supplier
certifies a class but does not specify a particular steel alloy.

## Mechanical property / strength selections

Use “Mechanical class” rather than an unqualified “Grade” label. Store the governing
standard alongside the code, because the same number can mean different things.

| Fastener / system | Candidate options | Treatment |
| --- | --- | --- |
| Metric steel bolts, screws, studs — ISO 898-1 | 4.6; 4.8; 5.6; 5.8; 6.8; 8.8; 9.8; 10.9; 12.9 | General class vocabulary; product geometry/diameter still constrain applicability |
| Reduced-loadability steel fasteners | 04.6; 04.8; 05.6; 05.8; 06.8; 08.8; 09.8; 010.9; 012.9 | Extended, distinct from full-loadability designations |
| Metric steel nuts — ISO 898-2:2022 | 04; 05; 5; 6; 8; 10; 12 | Style and diameter dependent; 04/05 are thin-nut classes |
| Older nut systems | 4; 9 | Legacy/other-standard entries, not current ISO 898-2:2022 defaults |
| Steel set screws — ISO 898-5 | 14H; 22H; 33H; 45H | Hardness classes, not tensile bolt classes |
| Flat steel washers — ISO 898-3 | 100HV; 200HV; 300HV; 380HV | 380HV is an extended purchaser/supplier-agreed case in the cited edition |
| Other washer specifications | 140HV and supplier-specified hardness ranges | Separate governing specification; do not label every hardness ISO 898-3 |
| Common stainless bolts/screws | A2-50; A2-70; A2-80; A4-50; A4-70; A4-80 | Store stainless group and property class separately; display the combined designation |
| Extended stainless | Other ISO 3506 groups and documented classes, including A8-100 | Enable individual pairs after checking the applicable standard/product; do not cross-join all groups with all classes |
| SAE J429 bolts | Grade 1; Grade 2; Grade 5; Grade 8 | Separate SAE namespace, not equivalents of metric classes |
| ASTM bolts / studs | A307 A/B; A193 B7/B8/B8M; A320 L7/L43; A354 BC/BD; A449; F1554 36/55/105; F3125 A325/A490; F593 | Preserve standard, grade and any required class/type/alloy-group qualification |
| ASTM nuts / washers | A194; A563; F594; F436; F844, with their applicable qualifications | Standard-specific extended selectors, not generic bolt-grade choices |
| Nonferrous / polymer fasteners | Not applicable; supplier-specified mechanical designation where one exists | Material alloy/temper may carry the relevant distinction; do not invent an ISO steel class |

Sources: [ISO 898-1 scope](https://www.iso.org/standard/60610.html) and
[Bossard marking table](https://www.bossard.com/-/media/bossard-group/website/documents/technical-resources/en/f-013-en.pdf);
[current ISO 898-2 scope and class list](https://www.iso.org/standard/79349.html);
[Bossard ISO 898-5 class discussion](https://www.bossard.com/nl-nl/-/media/bossard-group/website/documents/white-paper/bossard-whitepaper-addition-of-lead-en-07-2020.pdf);
[SIST's ISO 898-3 preview](https://preview.sist.si/sist-preview/63232/5508adcf7c374ce4a568748bfd778d49/ISO-898-3-2018.pdf);
[Bossard washer guide](https://www.bossard.com/nl-en/-/media/bossard-group/website/documents/technical-resources/en/f-040-en.pdf);
[ISO 3506-1 scope](https://www.iso.org/standard/70045.html);
[Portland Bolt grade table](https://www.portlandbolt.com/technical/strength-requirements-by-grade/) and
[specification index](https://www.portlandbolt.com/technical/specifications/), and
[stainless nut alloy groups](https://www.portlandbolt.com/technical/specifications/astm-f594/).

Important research result: many older supplier charts include nut classes 4 and 9.
ISO 898-2:2022 lists 04/05/5/6/8/10/12. Do not import an old chart as if it were the
current standard. Another distinction: ISO product grades A/B/C concern product
accuracy, not strength/property classes such as 8.8.

The complete stainless group/class matrix was not verified in this research pass:
the current Bossard PDF timed out. Keep those additional pairs pending validation,
even though the family vocabulary is useful. This document is a seed inventory,
not permission to claim conformity from selecting a dropdown value.

## Finish selections

| Group | Proposed selectable options |
| --- | --- |
| No added coating | Plain/uncoated; plain with protective oil |
| Conversion treatments | Black oxide; black oxide + oil; zinc phosphate; manganese phosphate; phosphate + oil |
| Electroplated zinc | Zinc plated, passivation unspecified; zinc + clear/blue passivation; zinc + yellow passivation; zinc + black passivation |
| Zinc alloys | Zinc-nickel; zinc-iron, with passivation/topcoat specified separately when known |
| Other zinc processes | Hot-dip galvanized; mechanically zinc plated; zinc-flake coating |
| Other metallic plating | Gold; nickel; nickel/chromium; copper; brass; bronze/copper-tin; silver; tin; tin-zinc; copper-nickel; copper-nickel-chromium; copper-silver |
| Stainless surface treatments | Passivated; electropolished; blackened stainless, where supplied |
| Aluminium / titanium treatments | Anodized, with colour/process specification when relevant |
| Organic / functional systems | PTFE-based coating; organic topcoat; dry-film lubricant; wax/lubricant; documented proprietary coating systems |
| Specialist / legacy | Cadmium plated and documented historical conversion systems; separate from common defaults |

Primary sources: [ISO 4042 electroplated systems](https://www.iso.org/standard/77913.html),
[ISO 10683 zinc-flake systems](https://committee.iso.org/standard/70609.html?browse=ics),
[Bossard corrosion-protection overview](https://www.bossard.com/global-en/knowledge-hub/resources/technical-information/corrosion-protection/),
[Simpson Strong-Tie materials/coatings](https://www.strongtie.com/products/fastening-systems/technical-notes/corrosion-information/materials-and-coatings-for-fasteners),
[Accu finish/coating inventory](https://www.accu.co.uk/c/23-finish-plating-and-coatings-information),
and [Accu aluminium anodizing options](https://www.accu.co.uk/p/33-aluminium).

A finish is often a coating system, not just a colour. Store process and any known
passivation, thickness, sealant/topcoat, lubricant and supplier designation.
Unknown details remain unknown. Do not infer conversion chemistry from yellow or
black appearance. Generic zinc plating, hot-dip galvanizing, mechanical zinc and
zinc flake remain distinct identities. Branded coating names remain supplier
systems, not automatic aliases of a generic process.

## Proposed ForgePDM implementation boundary

1. Read geometry from the workbench; present material/class/finish choices in one
   form. Derive the standard catalog name and description automatically.
2. Start with metric steel and common A2/A4 stainless, nuts, washers and set screws;
   include the extended inventory under an explicit searchable view.
3. Filter mechanical classes by family, standard, material, style and size as
   verified rules become available. Unverified combinations are not automatically
   certified or silently treated as equivalent.
4. Keep Unknown, Not applicable and Plain/uncoated distinct. Permit explicit
   incomplete registration under existing Working lifecycle rules.
5. Give each controlled option a stable ID, readable label, standard/edition,
   source, applicability and legacy status. User/admin extensions need review.
6. Preserve existing catalog identities and legacy strings. Changing the UI must
   not silently merge existing S items, change their specification or alter
   historical assembly associations. Plan compatibility before implementing.

No application code, database, installed addon or engineering data was changed by
this research. A complete compatibility matrix and detailed specialist alloy/
coating designations remain follow-up validation work.
