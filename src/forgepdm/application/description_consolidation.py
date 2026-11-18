"""Lossless schema-20 consolidation; legacy contexts remain available for history."""

import json
from uuid import uuid4


def consolidate(c):
    from forgepdm.application.localization import now, sync_item

    for item in c.execute("SELECT * FROM items").fetchall():
        revisions = c.execute(
            "SELECT id FROM item_revisions WHERE item_id=?", (item["id"],)
        ).fetchall()
        for revision in revisions:
            rid = revision["id"]
            previous = c.execute(
                "SELECT * FROM revision_descriptions WHERE revision_id=?", (rid,)
            ).fetchone()
            text = (
                previous["description"]
                if previous and previous["description"].strip()
                else item["description"] or item["name"]
            )
            # Never replace an assigned material snapshot with unrelated item text.
            if previous and previous["material_revision_id"]:
                text = previous["description"]
            c.execute(
                "INSERT INTO description_consolidation VALUES (?,?,?)",
                (
                    rid,
                    json.dumps(dict(previous)) if previous else None,
                    "revision"
                    if previous and previous["description"].strip()
                    else "legacy_item_text",
                ),
            )
            if previous:
                c.execute(
                    "UPDATE revision_descriptions SET description=? WHERE revision_id=?",
                    (text, rid),
                )
            else:
                c.execute(
                    "INSERT INTO revision_descriptions(revision_id,description) VALUES (?,?)",
                    (rid, text),
                )
        sync_item(c, item["id"])
        for revision in revisions:
            target = c.execute(
                "SELECT s.*,v.text,v.language FROM localized_text_sources s JOIN localized_source_versions v ON v.source_id=s.id AND v.version=s.current_version WHERE s.revision_id=? AND s.field='description'",
                (revision["id"],),
            ).fetchone()
            candidates = c.execute(
                "SELECT s.*,v.text,v.language FROM localized_text_sources s JOIN localized_source_versions v ON v.source_id=s.id AND v.version=s.current_version WHERE s.item_id=? AND s.revision_id IS NULL AND v.text=?",
                (item["id"], target["text"]),
            ).fetchall()
            languages = {s["language"] for s in candidates if s["language"] != "und"}
            locale = target["language"]
            if locale == "und" and len(languages) == 1:
                locale = languages.pop()
                target = dict(target)
                target["current_version"] += 1
                c.execute(
                    "UPDATE localized_text_sources SET current_version=? WHERE id=?",
                    (target["current_version"], target["id"]),
                )
                c.execute(
                    "INSERT INTO localized_source_versions VALUES (?,?,?,?,?,?)",
                    (target["id"], target["current_version"], locale, target["text"], None, now()),
                )
            rows = []
            for source in candidates:
                if source["language"] != locale or locale == "und":
                    continue
                rows.extend(
                    c.execute(
                        "SELECT * FROM localized_translation_versions WHERE source_id=? AND source_version=? AND superseded_at IS NULL",
                        (source["id"], source["current_version"]),
                    ).fetchall()
                )
            existing = c.execute(
                "SELECT * FROM localized_translation_versions WHERE source_id=? AND superseded_at IS NULL",
                (target["id"],),
            ).fetchall()
            for row in rows:
                peers = [
                    t
                    for t in [*rows, *existing]
                    if t["language"] == row["language"] and t["state"] == "approved"
                ]
                conflict = len({t["text"] for t in peers}) > 1
                if existing or any(
                    t["language"] == row["language"] and t["text"] == row["text"]
                    for t in rows
                    if t["id"] < row["id"]
                ):
                    continue
                provenance = {
                    "origin": "description_consolidation",
                    "copied_from": row["id"],
                    "original_provenance": json.loads(row["provenance_json"]),
                }
                c.execute(
                    "INSERT INTO localized_translation_versions VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL)",
                    (
                        str(uuid4()),
                        target["id"],
                        target["current_version"],
                        row["language"],
                        row["text"],
                        "needs_review" if conflict else row["state"],
                        json.dumps(provenance),
                        row["created_by"],
                        now(),
                        row["approved_by"],
                        row["approved_at"],
                    ),
                )


def mirror_legacy_change(c, legacy):
    """Bridge an old item-text editor only when it still describes the current revision."""
    from forgepdm.application.localization import now
    from forgepdm.domain.entities import Conflict

    target = c.execute(
        "SELECT s.*,v.text,v.language FROM localized_text_sources s JOIN items i ON i.current_revision_id=s.revision_id JOIN localized_source_versions v ON v.source_id=s.id AND v.version=s.current_version WHERE i.id=? AND s.field='description'",
        (legacy["item_id"],),
    ).fetchone()
    if not target or target["text"] != legacy["source"]["text"]:
        raise Conflict(
            "Legacy text differs from the revision description; reload using the description editor"
        )
    existing = c.execute(
        "SELECT * FROM localized_translation_versions WHERE source_id=? AND superseded_at IS NULL",
        (target["id"],),
    ).fetchall()
    if any(json.loads(t["provenance_json"]).get("legacy_source") != legacy["id"] for t in existing):
        raise Conflict(
            "Revision translations have independent changes; reload using the description editor"
        )
    version = target["current_version"]
    if target["language"] != legacy["source"]["language"]:
        version += 1
        c.execute(
            "UPDATE localized_text_sources SET current_version=? WHERE id=?",
            (version, target["id"]),
        )
        c.execute(
            "INSERT INTO localized_source_versions VALUES (?,?,?,?,?,?)",
            (target["id"], version, legacy["source"]["language"], target["text"], None, now()),
        )
    c.execute(
        "UPDATE localized_translation_versions SET superseded_at=? WHERE source_id=? AND superseded_at IS NULL",
        (now(), target["id"]),
    )
    for t in legacy["translations"]:
        if t["superseded_at"] is not None or t["source_version"] != legacy["current_version"]:
            continue
        c.execute(
            "INSERT INTO localized_translation_versions VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL)",
            (
                str(uuid4()),
                target["id"],
                version,
                t["language"],
                t["text"],
                t["state"],
                json.dumps(
                    {
                        "origin": "legacy_alias",
                        "legacy_source": legacy["id"],
                        "copied_from": t["id"],
                    }
                ),
                t["created_by"],
                now(),
                t["approved_by"],
                t["approved_at"],
            ),
        )
