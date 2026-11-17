"""Locale presentation never changes identity, engineering revisions or CAD tokens."""

import pytest

from forgepdm.application.catalog import CatalogService
from forgepdm.application.localization import LocalizationService, resolve
from forgepdm.domain.entities import Conflict, Forbidden, ItemKind, LifecycleState


def setup(b, locale="pt-BR"):
    item = b.items.create_item(
        kind=ItemKind.ASSEMBLY,
        name="Conjunto",
        description="Aço",
        created_by=b.users["editor"].id,
        project_id=b.project_id,
        source_language=locale,
    )
    return item, LocalizationService(b.database, b.authorization)


def source(svc, b, item):
    return next(s for s in svc.list(b.users["editor"], item.id) if s["field"] == "designation")


def test_manual_approval_draft_edit_and_source_correction(backend):
    b = backend
    item, svc = setup(b)
    s = source(svc, b, item)
    draft = svc.change(b.users["editor"], s["id"], "draft", s["token"], "en", "Assembly")
    with b.database.connection() as c:
        assert resolve(c, item.id, None, "designation", "en")["text"] == "Conjunto"
    approved = svc.change(
        b.users["editor"],
        s["id"],
        "approve",
        draft["token"],
        translation_id=draft["translations"][-1]["id"],
    )
    with b.database.connection() as c:
        assert resolve(c, item.id, None, "designation", "en")["text"] == "Assembly"
    updated = svc.change(b.users["editor"], s["id"], "draft", approved["token"], "en", "Module")
    with b.database.connection() as c:
        assert resolve(c, item.id, None, "designation", "en")["text"] == "Assembly"
    corrected = svc.change(b.users["editor"], s["id"], "correct-language", updated["token"], "en")
    assert all(t["state"] == "needs_review" for t in corrected["translations"])
    assert corrected["history"][0]["text"] == "Conjunto"
    with b.database.connection() as c:
        assert (
            c.execute("SELECT COUNT(*) FROM item_revisions WHERE item_id=?", (item.id,)).fetchone()[
                0
            ]
            == 1
        )


def test_legacy_unknown_and_permissions_and_stale_tokens(backend):
    b = backend
    item, svc = setup(b, None)
    s = source(svc, b, item)
    assert s["source"]["language"] == "und"
    with pytest.raises(Forbidden):
        svc.change(b.users["viewer"], s["id"], "draft", s["token"], "en", "Assembly")
    draft = svc.change(b.users["editor"], s["id"], "draft", s["token"], "en", "Assembly")
    with pytest.raises(Conflict):
        svc.change(
            b.users["editor"],
            s["id"],
            "approve",
            draft["token"],
            translation_id=draft["translations"][0]["id"],
        )
    with pytest.raises(Conflict):
        svc.change(b.users["editor"], s["id"], "draft", s["token"], "en", "Other")


def test_approved_search_accent_case_and_permissions(backend):
    b = backend
    item, svc = setup(b)
    s = source(svc, b, item)
    draft = svc.change(b.users["editor"], s["id"], "draft", s["token"], "en", "Assembly")
    catalog = CatalogService(b.database, b.authorization)
    assert not catalog.search_items(b.users["viewer"], query="Assembly", language="en")["items"]
    svc.change(
        b.users["editor"],
        s["id"],
        "approve",
        draft["token"],
        translation_id=draft["translations"][-1]["id"],
    )
    page = catalog.search_items(b.users["viewer"], query="ASSEMBLY", language="en", limit=1)
    assert page["items"][0]["id"] == item.id
    assert page["items"][0]["localized_name"]["text"] == "Assembly"
    assert catalog.search_items(b.users["viewer"], query="aco", language="pt-BR")["items"]


def test_source_edits_invalidate_and_revision_copy_retains_language(backend):
    from forgepdm.application.descriptions import DescriptionService

    b = backend
    item, svc = setup(b)
    descriptions = DescriptionService(b.database, b.authorization, b.revisions)
    current = descriptions.read(b.users["editor"], item.current_revision_id)
    descriptions.save(
        b.users["editor"], item.current_revision_id, "Montagem", None, current["token"]
    )
    revision_source = next(
        s
        for s in svc.list(b.users["editor"], item.id, item.current_revision_id)
        if s["field"] == "description"
    )
    draft = svc.change(
        b.users["editor"],
        revision_source["id"],
        "draft",
        revision_source["token"],
        "en",
        "Assembly",
    )
    svc.change(
        b.users["editor"],
        revision_source["id"],
        "approve",
        draft["token"],
        translation_id=draft["translations"][-1]["id"],
    )
    current = descriptions.read(b.users["editor"], item.current_revision_id)
    descriptions.save(
        b.users["editor"], item.current_revision_id, "Outra montagem", None, current["token"]
    )
    with b.database.connection() as c:
        assert (
            resolve(c, item.id, item.current_revision_id, "description", "en")["text"]
            == "Outra montagem"
        )
    b.revisions.check_in(b.users["editor"], item.current_revision_id)
    b.revisions.transition_lifecycle(
        b.users["editor"], item.current_revision_id, LifecycleState.RELEASED
    )
    newer, _ = b.revisions.create_next_revision(b.users["editor"], item.id, "Next")
    result = next(
        s for s in svc.list(b.users["editor"], item.id, newer.id) if s["field"] == "description"
    )
    assert result["source"]["language"] == "pt-BR"


def test_generation_preserves_specification_tokens():
    from forgepdm.domain.description_generation import generate

    spec = {
        "geometry": {"Type": "ISO4017", "Diameter": "M8", "Length": "20"},
        "material": "steel",
        "grade": "8.8",
        "finish": "plain",
    }
    value = generate(spec, "pt-BR")
    assert "PARAFUSO" in value["text"] and "ISO4017" in value["text"] and "8.8" in value["text"]
    assert value["state"] == "draft" and spec["geometry"]["Type"] == "ISO4017"


def test_api_locale_fields_and_legacy_description_token(backend, monkeypatch):
    from fastapi.testclient import TestClient

    from forgepdm.api.v1.routes import current_user
    from forgepdm.main import create_app

    b = backend
    monkeypatch.setenv("FORGEPDM_FILE_ROOT", str(b.storage.root))
    app = create_app(b.database.path)
    app.dependency_overrides[current_user] = lambda: b.users["editor"]
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/items",
            json={
                "kind": "assembly",
                "name": "Conjunto",
                "description": "Aço",
                "project_id": b.project_id,
                "source_language": "pt-BR",
            },
        )
        assert response.status_code == 201, response.text
        item = response.json()
        path = f"/api/v1/items/{item['id']}/localized-texts"
        records = client.get(path, params={"language": "en"}).json()
        assert records[0]["source"]["language"] == "pt-BR"
        before = client.get(f"/api/v1/revisions/{item['current_revision_id']}/description").json()
        s = next(r for r in records if r["field"] == "designation")
        draft = client.post(
            "/api/v1/localized-texts/" + s["id"],
            json={
                "operation": "draft",
                "language": "en",
                "text": "Assembly",
                "expected_token": s["token"],
            },
        ).json()
        approved = client.post(
            "/api/v1/localized-texts/" + s["id"],
            json={
                "operation": "approve",
                "translation_id": draft["translations"][0]["id"],
                "expected_token": draft["token"],
            },
        )
        assert approved.status_code == 200, approved.text
        assert (
            client.get(f"/api/v1/revisions/{item['current_revision_id']}/description").json()
            == before
        )
        assert (
            client.get("/api/v1/items", params={"q": "Assembly", "language": "en"}).json()["items"][
                0
            ]["localized_name"]["text"]
            == "Assembly"
        )


def test_translation_after_release_and_disabled_actor(backend):
    b = backend
    item, svc = setup(b)
    s = source(svc, b, item)
    b.revisions.check_in(b.users["editor"], item.current_revision_id)
    b.revisions.transition_lifecycle(
        b.users["editor"], item.current_revision_id, LifecycleState.RELEASED
    )
    draft = svc.change(b.users["editor"], s["id"], "draft", s["token"], "en", "Assembly")
    svc.change(
        b.users["editor"],
        s["id"],
        "approve",
        draft["token"],
        translation_id=draft["translations"][0]["id"],
    )
    with b.database.transaction() as c:
        c.execute("UPDATE users SET enabled=0 WHERE id=?", (b.users["editor"].id,))
    s = source(svc, b, item)
    with pytest.raises(Forbidden):
        svc.change(b.users["editor"], s["id"], "draft", s["token"], "en", "Different")


def test_english_generator_matches_existing_contract(monkeypatch):
    from pathlib import Path

    from forgepdm.domain.description_generation import generate

    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "clients/freecad"))
    from freecad.forgepdm.standard_options import catalog_text

    for material, grade, finish in [("steel", "8.8", "plain"), (None, None, None)]:
        spec = {
            "geometry": {"Type": "ISO4017", "Diameter": "M8", "Length": "20"},
            "material": material,
            "grade": grade,
            "finish": finish,
        }
        assert generate(spec, "en")["text"] == catalog_text(spec, "SCREW", "HEX HEAD")[0]


def test_localized_bom_tokens_and_exact_snapshot_are_stable(backend):
    import copy

    from test_assembly_mass import setup as assembly_setup

    from forgepdm.application.bom_reports import bom_report

    b = backend
    root, child, screw, _, _ = assembly_setup(b)
    svc = LocalizationService(b.database, b.authorization)
    s = source(svc, b, screw)
    s = svc.change(b.users["editor"], s["id"], "correct-language", s["token"], "en")
    s = svc.change(b.users["editor"], s["id"], "draft", s["token"], "pt-BR", "Parafuso")
    svc.change(
        b.users["editor"],
        s["id"],
        "approve",
        s["token"],
        translation_id=s["translations"][-1]["id"],
    )

    def read(locale=None):
        return bom_report(
            b.database, b.authorization, b.users["editor"], root.current_revision_id, locale
        )

    original = read()
    translated = read("pt-BR")
    assert translated["token"] == read("pt-BR")["token"]
    frozen = copy.deepcopy(translated)
    row = translated["views"]["flattened"][0]
    assert row["item_name"] == "Parafuso" and row["localization"]["designation"]["translation_id"]
    assert row["component_revision_id"] == screw.current_revision_id
    s = source(svc, b, screw)
    svc.change(b.users["editor"], s["id"], "draft", s["token"], "pt-BR", "New draft")
    assert read("pt-BR")["token"] == translated["token"]
    assert frozen == translated
    assert original["token"] == read()["token"]
    assert original["mass"] == translated["mass"]


def test_material_translation_is_a_reviewed_copy_not_a_live_pointer(backend):
    from conftest import create_item

    from forgepdm.application.descriptions import DescriptionService

    b = backend
    user = b.users["editor"]
    svc = LocalizationService(b.database, b.authorization)
    descriptions = DescriptionService(b.database, b.authorization, b.revisions)
    material = b.items.create_item(
        kind=ItemKind.PART,
        number_series="M",
        name="Chapa de aço",
        description="Chapa de aço",
        source_language="pt-BR",
        created_by=user.id,
    )
    m = next(
        s
        for s in svc.list(user, material.id, material.current_revision_id)
        if s["field"] == "description"
    )
    m = svc.change(user, m["id"], "draft", m["token"], "en", "Steel plate")
    svc.change(user, m["id"], "approve", m["token"], translation_id=m["translations"][-1]["id"])
    part = create_item(b)
    descriptions.save(
        user,
        part.current_revision_id,
        "",
        material.current_revision_id,
        descriptions.read(user, part.current_revision_id)["token"],
    )
    p = next(
        s for s in svc.list(user, part.id, part.current_revision_id) if s["field"] == "description"
    )
    assert p["source"]["language"] == "pt-BR"
    p = svc.change(user, p["id"], "generate", p["token"], "en")
    assert p["translations"][-1]["state"] == "draft"
    p = svc.change(user, p["id"], "approve", p["token"], translation_id=p["translations"][-1]["id"])
    descriptions.save(
        user,
        material.current_revision_id,
        "Outra chapa",
        None,
        descriptions.read(user, material.current_revision_id)["token"],
    )
    with b.database.connection() as c:
        assert (
            resolve(c, part.id, part.current_revision_id, "description", "en")["text"]
            == "Steel plate"
        )
    with pytest.raises(Conflict):
        svc.change(user, p["id"], "generate", p["token"], "en")


def test_read_permissions_tokens_and_search_pagination(backend):
    b = backend
    svc = LocalizationService(b.database, b.authorization)
    for index in range(3):
        item, _ = setup(b)
        s = source(svc, b, item)
        assert s["can_edit"]
        assert not svc.list(b.users["viewer"], item.id)[0]["can_edit"]
        s = svc.change(b.users["editor"], s["id"], "draft", s["token"], "en", "Unique translation")
        svc.change(
            b.users["editor"],
            s["id"],
            "approve",
            s["token"],
            translation_id=s["translations"][-1]["id"],
        )
    catalog = CatalogService(b.database, b.authorization)
    first = catalog.search_items(
        b.users["viewer"], query="Unique translation", limit=2, language="pt-BR"
    )
    second = catalog.search_items(
        b.users["viewer"], query="Unique translation", limit=2, offset=2, language="pt-BR"
    )
    assert len(first["items"]) == 2 and first["has_more"]
    assert len(second["items"]) == 1 and not second["has_more"]
    assert {i["id"] for i in first["items"]}.isdisjoint({i["id"] for i in second["items"]})
    with b.database.transaction() as c:
        c.execute("DELETE FROM project_items WHERE item_id=?", (item.id,))
    with pytest.raises(Forbidden):
        svc.list(b.users["viewer"], item.id)
