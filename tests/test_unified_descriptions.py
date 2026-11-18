"""Single description behavior and lossless legacy consolidation."""

import json

import pytest

from forgepdm.application.descriptions import DescriptionService
from forgepdm.application.localization import LocalizationService
from forgepdm.domain.entities import Conflict, ItemKind


def create(b, series, text="Component", **kwargs):
    return b.items.create_item(
        kind=ItemKind.ASSEMBLY if series == "A" else ItemKind.PART,
        number_series=series,
        name=text,
        description="",
        created_by=b.users["editor"].id,
        project_id=b.project_id if series in ("A", "P") else None,
        source_language="en",
        **kwargs,
    )


def test_manual_part_material_and_clear(backend):
    b = backend
    svc = DescriptionService(b.database, b.authorization, b.revisions)
    p = create(b, "P")
    m = create(b, "M", "Steel plate")

    def save(text, pin=None):
        return svc.save(
            b.users["editor"],
            p.current_revision_id,
            text,
            pin,
            svc.read(b.users["editor"], p.current_revision_id)["token"],
        )

    assert save("Guardrail clamp")["description"] == "Guardrail clamp"
    assert save("", m.current_revision_id)["description"] == "Steel plate"
    assert save("")["description"] == ""
    assert save("Manual clamp")["description"] == "Manual clamp"


@pytest.mark.parametrize("series", ["P", "A", "S", "M"])
def test_every_type_has_one_revision_description(backend, series):
    b = backend
    item = create(b, series)
    sources = LocalizationService(b.database, b.authorization).list(
        b.users["editor"], item.id, item.current_revision_id
    )
    assert len([s for s in sources if s["field"] == "description"]) == 1
    assert next(s for s in sources if s["field"] == "description")["source"]["text"] == "Component"


def test_structured_description_cannot_be_overridden(backend):
    b = backend
    item = create(
        b,
        "S",
        standard_specification=dict(
            geometry=dict(Type="ISO4017", Diameter="M8"),
            material="steel",
            grade="8.8",
            finish="plain",
        ),
    )
    svc = DescriptionService(b.database, b.authorization, b.revisions)
    with pytest.raises(Conflict, match="fixed"):
        svc.save(
            b.users["editor"],
            item.current_revision_id,
            "Different",
            None,
            svc.read(b.users["editor"], item.current_revision_id)["token"],
        )


def test_consolidation_preserves_legacy_approved_translation(backend):
    b = backend
    item = create(b, "A", "Assembly")
    svc = LocalizationService(b.database, b.authorization)
    source = next(s for s in svc.list(b.users["editor"], item.id) if s["field"] == "designation")
    result = svc.change(
        b.users["editor"], source["id"], "draft", source["token"], "pt-BR", "Montagem"
    )
    approved = svc.change(
        b.users["editor"],
        source["id"],
        "approve",
        result["token"],
        translation_id=result["translations"][-1]["id"],
    )
    with b.database.transaction() as c:
        c.execute(
            "DELETE FROM localized_translation_versions WHERE source_id IN (SELECT id FROM localized_text_sources WHERE revision_id=?)",
            (item.current_revision_id,),
        )
        c.execute(
            "DELETE FROM localized_source_versions WHERE source_id IN (SELECT id FROM localized_text_sources WHERE revision_id=?)",
            (item.current_revision_id,),
        )
        c.execute(
            "DELETE FROM localized_text_sources WHERE revision_id=?", (item.current_revision_id,)
        )
        c.execute(
            "DELETE FROM revision_descriptions WHERE revision_id=?", (item.current_revision_id,)
        )
        c.execute("DROP TABLE description_consolidation")
        c.execute("DELETE FROM schema_version WHERE version=20")
    b.database.initialize()
    b.database.initialize()
    current = next(
        s
        for s in svc.list(b.users["editor"], item.id, item.current_revision_id)
        if s["field"] == "description"
    )
    assert current["source"]["text"] == "Assembly"
    assert current["translations"][0]["text"] == "Montagem"
    assert current["translations"][0]["state"] == "approved"
    assert (
        json.loads(current["translations"][0]["provenance_json"])["copied_from"]
        == approved["translations"][0]["id"]
    )
    assert (
        next(s for s in svc.list(b.users["editor"], item.id) if s["field"] == "designation")[
            "translations"
        ]
        == approved["translations"]
    )
