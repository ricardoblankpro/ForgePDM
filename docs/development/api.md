# API contracts

The running backend's `/docs` and `/openapi.json` are authoritative route/field
references. Application services own domain policy; client code must not duplicate
permission, transaction or revision rules. Routes below are relative to `/api/v1`.

## Authentication and reads

Login returns an opaque bearer token; send it as `Authorization: Bearer TOKEN`.
Sessions are revocable and expire. New/reset accounts must change temporary
passwords before engineering requests. Read authorization is evaluated before
returning catalog results, reports, datasets, dependencies or downloads.

Catalog reads use `/projects`, `/items`, `/items/{id}/revisions` and
`/revisions/{id}`. Pagination returns `items`, `limit`, `offset` and `has_more`;
filters and paging respect project/library permissions. Requests for an exact
historical revision do not substitute the current revision.

## Stored BOM and reports

`/revisions/{id}/bom?recursive=true` is the existing nested structure contract;
its quantities are per immediate parent. Reviewed synchronization uses a current
editable snapshot and lease token rather than treating a report as an edit plan.

`/revisions/{id}/bom-report` returns `views.direct`, `views.indented` and
`views.flattened` from one read snapshot, with common `token`, `generated_at`,
`mass`, `structure_complete` and `structure_issues`. Row `quantity`,
`total_quantity` and `total_mass` refer to one root assembly.
`quantity_per_parent` is null for aggregated flattened rows. Source occurrence
paths retain provenance; report indices are not stored BOM positions.

The compatibility `/drawing-bom` route projects Direct and `/assembly-mass`
projects its shared leaf summary. These thin wrappers protect existing clients.
See [report semantics](../user/bom.md) and ADR-022.

## Protected writes and recovery

Dataset attachment, immutable manifest writes and check-in require exact current
checkout UUID/version. Native check-in commits CAD/evidence/manifest and checkout
release atomically through explicit protected part/assembly routes. Actor-scoped
operation UUIDs, exact source pins and durable client journals recover lost
responses. Reuse an operation ID only for identical intent; query its status
before starting another operation. Revision creation requires a change note and
expected source revision. PDF publication binds each derived file to its exact
native source. See ADR-008, ADR-009 and ADR-019 in the [decision index](../decisions/README.md).

## Engineering enrichment and compatibility

Description, physical-material, part mass and S reference-mass APIs expose
source evidence and concurrency tokens. Backend capabilities indicate support;
clients reject missing protected capabilities rather than weakening guarantees.
Supplier network requests occur outside transactions, with final permission,
lease and specification checks. Source priority is documented in [materials](../user/materials.md).

Advanced material specifications/inputs, requirements snapshots and their stored
records remain supported compatibility surfaces. Their absence from the ordinary
UI is not authorization to delete their APIs or migration history. API changes
need service/API tests and explicit compatibility notes.

## Thumbnail derivatives

`POST /api/v1/files/{source_file_id}/thumbnail` attaches one immutable
`isometric-v1` PNG to an exact native CAD file. JSON fields are
`source_content_hash`, `render_profile` and `png_base64` (at most 1 MiB decoded).
Only the enabled uploader or an administrator with current editor access can
attach. This auxiliary operation needs no checkout and may complete after release;
CAD writes retain all existing checkout/lifecycle rules. Identical image/source
intent replays successfully; replacement conflicts. PNG decoding/re-encoding is
bounded to 512px per side, one frame and limited text metadata.

`GET /api/v1/files/{source_file_id}/thumbnail` inherits the source revision's read
permission and returns PNG bytes, source/hash identity headers and private/no-store
policy. Missing or inaccessible images return 404. The image `files` row is not
an independently downloadable dataset. See
[ADR-025](../decisions/ADR-025-immutable-isometric-thumbnails.md).

## Description localization

`POST /items` accepts optional `source_language` (`en`, `pt-BR`); omitted metadata
remains `und` for old clients. Legacy response fields and description concurrency
tokens retain their existing meaning. `GET /languages` returns supported tags.

`GET /items/{id}/localized-texts?revision_id=…&language=pt-BR` returns source contexts,
source history, translation versions, `can_edit`, optimistic `token`, and optional
`resolved` presentation (text, fallback, source version and translation ID).
`GET /revisions/{id}/localized-texts` is a context convenience route.

`POST /localized-texts/{source_id}` accepts `operation` (`draft`, `generate`,
`approve`, `correct-language`), `expected_token`, optional `language`, `text` and
`translation_id`. Approval targets a saved current draft. Conflicts return 409;
invalid language/input 422; permissions 403. `POST /description-proposals` accepts
`specification` plus `language` and returns draft text, warnings and provenance.
No mutation is made by requesting a standalone proposal.

`GET /items?language=pt-BR` adds `localized_name`/`localized_description` while
retaining canonical fields. Search includes approved translations in any language.
`GET /revisions/{id}/bom-report?language=pt-BR` adds language/provenance and presents
translated row text; omitted language preserves the original report contract.
See [review and snapshot semantics](../user/localization.md) and
[ADR-026](../decisions/ADR-026-versioned-item-description-localization.md).
