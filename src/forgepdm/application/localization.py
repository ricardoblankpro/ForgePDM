"""Versioned original text and optional, reviewed presentation translations."""

import hashlib
import json
import unicodedata
from datetime import datetime, timezone
from uuid import uuid4

from forgepdm.domain.entities import Conflict, Forbidden, NotFound

LANGUAGES = {"en": "English", "pt-BR": "Português (Brasil)"}


def language(value, unknown=False):
    if value is None and unknown:
        return "und"
    aliases = {k.casefold(): k for k in LANGUAGES}
    if unknown:
        aliases["und"] = "und"
    if not isinstance(value, str) or value.casefold() not in aliases:
        raise ValueError("unsupported description language")
    return aliases[value.casefold()]


def search_key(text):
    return "".join(
        c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c)
    )


def now():
    return datetime.now(timezone.utc).isoformat()


def sync_item(c, item_id, actor=None, locale=None):
    item = c.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    slots = [(None, "designation", item["name"]), (None, "master_description", item["description"])]
    slots += [
        (r["revision_id"], "description", r["description"])
        for r in c.execute(
            "SELECT d.* FROM revision_descriptions d JOIN item_revisions r ON r.id=d.revision_id WHERE r.item_id=?",
            (item_id,),
        )
    ]
    for revision, field, text in slots:
        source = c.execute(
            "SELECT * FROM localized_text_sources WHERE item_id=? AND revision_id IS ? AND field=?",
            (item_id, revision, field),
        ).fetchone()
        if source:
            current = c.execute(
                "SELECT * FROM localized_source_versions WHERE source_id=? AND version=?",
                (source["id"], source["current_version"]),
            ).fetchone()
            if current["text"] == text:
                continue
            sid, version, source_language = (
                source["id"],
                source["current_version"] + 1,
                current["language"],
            )
            c.execute(
                "UPDATE localized_translation_versions SET state='needs_review' WHERE source_id=? AND superseded_at IS NULL",
                (sid,),
            )
            c.execute(
                "UPDATE localized_text_sources SET current_version=? WHERE id=?", (version, sid)
            )
        else:
            sid, version, source_language = str(uuid4()), 1, locale or item["source_language"]
            c.execute(
                "INSERT INTO localized_text_sources VALUES (?,?,?,?,?)",
                (sid, item_id, revision, field, version),
            )
        if revision:
            material = c.execute(
                "SELECT material_revision_id FROM revision_descriptions WHERE revision_id=?",
                (revision,),
            ).fetchone()
            if material and material[0]:
                inherited = c.execute(
                    "SELECT v.language,v.text FROM localized_text_sources s JOIN localized_source_versions v ON v.source_id=s.id AND v.version=s.current_version WHERE s.revision_id=? AND s.field='description'",
                    (material[0],),
                ).fetchone()
                if inherited and inherited["text"] == text:
                    source_language = inherited["language"]
        c.execute(
            "INSERT INTO localized_source_versions VALUES (?,?,?,?,?,?)",
            (sid, version, source_language, text, actor, now()),
        )


def resolve(c, item_id, revision_id, field, requested):
    requested = language(requested)
    row = c.execute(
        "SELECT s.id,s.current_version,v.language,v.text FROM localized_text_sources s JOIN localized_source_versions v ON v.source_id=s.id AND v.version=s.current_version WHERE s.item_id=? AND s.revision_id IS ? AND s.field=?",
        (item_id, revision_id, field),
    ).fetchone()
    if row is None:
        return None
    translation = (
        c.execute(
            "SELECT id,text FROM localized_translation_versions WHERE source_id=? AND source_version=? AND language=? AND state='approved' AND superseded_at IS NULL ORDER BY approved_at DESC,id DESC LIMIT 1",
            (row["id"], row["current_version"], requested),
        ).fetchone()
        if requested != row["language"]
        else None
    )
    return {
        "text": translation["text"] if translation else row["text"],
        "original_text": row["text"],
        "requested_language": requested,
        "resolved_language": requested if translation else row["language"],
        "fallback": translation is None and requested != row["language"],
        "source_id": row["id"],
        "source_version": row["current_version"],
        "translation_id": translation["id"] if translation else None,
    }


def description(c, item_id, revision_id, requested):
    return resolve(c, item_id, revision_id, "description", requested)


class LocalizationService:
    def __init__(self, database, authorization):
        self.database, self.authorization = database, authorization

    def read_in(self, c, user, sid, write=False):
        row = c.execute("SELECT * FROM localized_text_sources WHERE id=?", (sid,)).fetchone()
        if row is None:
            raise NotFound("description source not found")
        rid = (
            row["revision_id"]
            or c.execute(
                "SELECT current_revision_id FROM items WHERE id=?", (row["item_id"],)
            ).fetchone()[0]
        )
        self.authorization.require_read_revision(user, rid, c)
        if write:
            actor = c.execute("SELECT enabled FROM users WHERE id=?", (user.id,)).fetchone()
            if not actor or not actor[0]:
                raise Forbidden("enabled editor required")
            self.authorization.require_manage_revision(user, rid, c)
        versions = [
            dict(v)
            for v in c.execute(
                "SELECT * FROM localized_source_versions WHERE source_id=? ORDER BY version", (sid,)
            )
        ]
        translations = [
            dict(t)
            for t in c.execute(
                "SELECT * FROM localized_translation_versions WHERE source_id=? ORDER BY created_at,id",
                (sid,),
            )
        ]
        result = {
            **dict(row),
            "source": versions[-1],
            "history": versions,
            "translations": translations,
        }
        result["token"] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
        try:
            actor = c.execute("SELECT enabled FROM users WHERE id=?", (user.id,)).fetchone()
            self.authorization.require_manage_revision(user, rid, c)
            result["can_edit"] = bool(actor and actor[0])
        except Forbidden:
            result["can_edit"] = False
        return result

    def list(self, user, item_id, revision_id=None, requested=None):
        with self.database.connection() as c:
            c.execute("BEGIN")
            self.authorization.require_read_item(user, item_id)
            if revision_id:
                self.authorization.require_read_revision(user, revision_id, c)
                if (
                    c.execute(
                        "SELECT item_id FROM item_revisions WHERE id=?", (revision_id,)
                    ).fetchone()[0]
                    != item_id
                ):
                    raise Conflict("revision belongs to another item")
            ids = [
                r[0]
                for r in c.execute(
                    "SELECT id FROM localized_text_sources WHERE item_id=? AND (revision_id IS NULL OR revision_id=?) ORDER BY field",
                    (item_id, revision_id),
                )
            ]
            result = [self.read_in(c, user, sid) for sid in ids]
            if requested:
                for source in result:
                    source["resolved"] = resolve(
                        c, item_id, source["revision_id"], source["field"], requested
                    )
            return result

    def change(
        self,
        user,
        sid,
        operation,
        expected_token,
        target_language=None,
        text=None,
        translation_id=None,
    ):
        with self.database.transaction() as c:
            current = self.read_in(c, user, sid, write=True)
            if current["token"] != expected_token:
                raise Conflict("description or translations changed; reload before saving")
            version = current["current_version"]
            provenance = {"origin": "manual"}
            if operation == "correct-language":
                locale = language(target_language)
                if locale == current["source"]["language"]:
                    return current
                c.execute(
                    "INSERT INTO localized_source_versions VALUES (?,?,?,?,?,?)",
                    (sid, version + 1, locale, current["source"]["text"], user.id, now()),
                )
                c.execute(
                    "UPDATE localized_text_sources SET current_version=? WHERE id=?",
                    (version + 1, sid),
                )
                c.execute(
                    "UPDATE localized_translation_versions SET state='needs_review' WHERE source_id=? AND superseded_at IS NULL",
                    (sid,),
                )
                if current["field"] == "designation":
                    c.execute(
                        "UPDATE items SET source_language=? WHERE id=?",
                        (locale, current["item_id"]),
                    )
            elif operation in ("draft", "generate"):
                locale = language(target_language)
                if locale == current["source"]["language"]:
                    raise ValueError("translate into a different language")
                if operation == "generate":
                    from forgepdm.domain.description_generation import generate

                    spec = c.execute(
                        "SELECT specification_json FROM standard_specifications WHERE item_id=?",
                        (current["item_id"],),
                    ).fetchone()
                    if spec and current["field"] in (
                        "description",
                        "designation",
                        "master_description",
                    ):
                        proposal = generate(json.loads(spec[0]), locale)
                    else:
                        material = c.execute(
                            "SELECT d.material_revision_id,r.item_id FROM revision_descriptions d JOIN item_revisions r ON r.id=d.material_revision_id WHERE d.revision_id=?",
                            (current["revision_id"],),
                        ).fetchone()
                        if not material or current["field"] != "description":
                            raise ValueError(
                                "generate a standard-part or pinned material proposal, or enter text manually"
                            )
                        self.authorization.require_read_revision(user, material[0], c)
                        inherited = resolve(c, material[1], material[0], "description", locale)
                        if (
                            not inherited
                            or inherited["fallback"]
                            or inherited["original_text"] != current["source"]["text"]
                        ):
                            raise Conflict(
                                "pinned material has no matching reviewed description in this language"
                            )
                        proposal = {
                            "text": inherited["text"],
                            "provenance": {"origin": "material_snapshot", **inherited},
                        }
                    text, provenance = proposal["text"], proposal["provenance"]
                if not isinstance(text, str) or not text.strip() or len(text) > 1000:
                    raise ValueError("translation must contain 1 to 1000 characters")
                c.execute(
                    "UPDATE localized_translation_versions SET superseded_at=? WHERE source_id=? AND language=? AND state IN ('draft','needs_review') AND superseded_at IS NULL",
                    (now(), sid, locale),
                )
                translation_id = str(uuid4())
                c.execute(
                    "INSERT INTO localized_translation_versions(id,source_id,source_version,language,text,state,provenance_json,created_by,created_at) VALUES (?,?,?,?,?,'draft',?,?,?)",
                    (
                        translation_id,
                        sid,
                        version,
                        locale,
                        text.strip(),
                        json.dumps(provenance, sort_keys=True),
                        user.id,
                        now(),
                    ),
                )
            elif operation == "approve":
                row = c.execute(
                    "SELECT * FROM localized_translation_versions WHERE id=? AND source_id=?",
                    (translation_id, sid),
                ).fetchone()
                if (
                    not row
                    or row["source_version"] != version
                    or row["state"] != "draft"
                    or row["superseded_at"] is not None
                ):
                    raise Conflict("approve a current draft against the current source")
                if current["source"]["language"] == "und":
                    raise Conflict("confirm the source language before approval")
                c.execute(
                    "UPDATE localized_translation_versions SET superseded_at=? WHERE source_id=? AND language=? AND state='approved' AND superseded_at IS NULL",
                    (now(), sid, row["language"]),
                )
                c.execute(
                    "UPDATE localized_translation_versions SET state='approved',approved_by=?,approved_at=? WHERE id=?",
                    (user.id, now(), translation_id),
                )
            else:
                raise ValueError("unsupported localization operation")
            c.execute(
                "INSERT INTO audit_events(id,actor_id,event_type,entity_type,entity_id,occurred_at,details_json) VALUES (?,?,?,?,?,?,?)",
                (
                    str(uuid4()),
                    user.id,
                    "localization." + operation,
                    "LocalizedText",
                    sid,
                    now(),
                    json.dumps(
                        {
                            "language": row["language"]
                            if operation == "approve"
                            else target_language,
                            "translation_id": translation_id,
                            "source_version": version + 1
                            if operation == "correct-language"
                            else version,
                        }
                    ),
                ),
            )
            result = self.read_in(c, user, sid)
            if current["revision_id"] is None:
                from forgepdm.application.description_consolidation import mirror_legacy_change

                mirror_legacy_change(c, result)
            return result


def carry_revision(c, item_id, old_revision, new_revision, actor):
    sync_item(c, item_id, actor)
    old = c.execute(
        "SELECT * FROM localized_text_sources WHERE revision_id=? AND field='description'",
        (old_revision,),
    ).fetchone()
    new = c.execute(
        "SELECT * FROM localized_text_sources WHERE revision_id=? AND field='description'",
        (new_revision,),
    ).fetchone()
    if not old or not new:
        return
    original = c.execute(
        "SELECT * FROM localized_source_versions WHERE source_id=? AND version=?",
        (old["id"], old["current_version"]),
    ).fetchone()
    target = c.execute(
        "SELECT * FROM localized_source_versions WHERE source_id=? AND version=?",
        (new["id"], new["current_version"]),
    ).fetchone()
    if original["text"] != target["text"]:
        return
    c.execute(
        "UPDATE localized_source_versions SET language=? WHERE source_id=? AND version=?",
        (original["language"], new["id"], new["current_version"]),
    )
    for row in c.execute(
        "SELECT * FROM localized_translation_versions WHERE source_id=? AND source_version=? AND superseded_at IS NULL",
        (old["id"], old["current_version"]),
    ).fetchall():
        provenance = json.loads(row["provenance_json"])
        provenance["copied_from"] = row["id"]
        c.execute(
            "INSERT INTO localized_translation_versions VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL)",
            (
                str(uuid4()),
                new["id"],
                new["current_version"],
                row["language"],
                row["text"],
                row["state"],
                json.dumps(provenance),
                actor,
                now(),
                row["approved_by"],
                row["approved_at"],
            ),
        )


def localized_catalog(catalog, user, query, project, series, limit, offset, requested):
    requested = language(requested)
    if len(query) > 200:
        raise ValueError("search text exceeds limits")
    page = catalog.search_items(
        user, query=query, project_id=project, number_series=series, limit=limit, offset=offset
    )
    records = page["items"]
    matches = []
    with catalog.database.connection() as c:
        c.execute("BEGIN")
        for record in records:
            catalog.authorization.require_read_revision(user, record["current_revision_id"], c)
            desc = description(c, record["id"], record["current_revision_id"], requested)
            matches.append({**record, "localized_name": desc, "localized_description": desc})
    return {
        "items": matches,
        "limit": limit,
        "offset": offset,
        "has_more": page["has_more"],
    }


def localize_report(c, report, requested):
    requested = language(requested)
    cache = {}
    for rows in report["views"].values():
        for row in rows:
            item_id, rid = row["item_id"], row["component_revision_id"]
            if rid not in cache:
                cache[rid] = (
                    description(c, item_id, rid, requested),
                    description(c, item_id, rid, requested),
                )
            name, desc = cache[rid]
            row["localization"] = {"designation": name, "description": desc}
            if name:
                row["item_name"] = name["text"]
            if desc:
                row["description"] = desc["text"]
            if row.get("number_series") == "P" and row.get("material") and desc:
                row["material"] = desc["text"]
    report["language"] = requested
    report["token"] = hashlib.sha256(
        json.dumps(
            {k: v for k, v in report.items() if k not in ("token", "generated_at")},
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()
