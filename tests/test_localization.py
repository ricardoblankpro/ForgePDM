"""Locale presentation never changes identity, engineering revisions or CAD tokens."""

import json
from pathlib import Path

import pytest

from forgepdm.application.catalog import CatalogService
from forgepdm.application.localization import LocalizationService, resolve
from forgepdm.domain.entities import Conflict, Forbidden, ItemKind, LifecycleState
from forgepdm.domain.standard_parts import specification


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


# The shared registry stays independent of every language vocabulary.
FASTENER_DOMAIN = Path(__file__).parents[1] / "src/forgepdm/domain"
FASTENER_NORMS = json.loads((FASTENER_DOMAIN / "fastener_terms.json").read_text())["norms"]
PT_BR_TERMS = json.loads(
    (FASTENER_DOMAIN / "fastener_locales/pt-BR.json").read_text(encoding="utf-8")
)


def fastener_spec(norm="ISO4017", **changes):
    return {
        "geometry": {"Type": norm, "Diameter": "M8", "PitchCustom": "1.25", "Length": "20"},
        "material": "steel",
        "grade": "8.8",
        "finish": "plain",
        **changes,
    }


@pytest.mark.parametrize("norm,pair", FASTENER_NORMS.items(), ids=FASTENER_NORMS)
def test_every_fastener_standard_has_portuguese_type_and_family(norm, pair):
    from forgepdm.domain.description_generation import generate

    kind, family = pair
    assert PT_BR_TERMS["types"][kind]
    assert PT_BR_TERMS["families"][family]
    proposal = generate(fastener_spec(norm), "pt-BR")
    assert proposal["text"].startswith(PT_BR_TERMS["types"][kind] + " AÇO ")
    assert PT_BR_TERMS["families"][family] + " " + norm in proposal["text"]
    assert proposal["warnings"] == []
    assert proposal["state"] == "draft"


@pytest.mark.parametrize(
    "norm,kind,family,diameter,pitch,length,grade",
    [
        ("ISO4017", "PARAFUSO", "CABEÇA SEXTAVADA", "M8", "1.25", "20", "8.8"),
        ("DIN914", "PARAFUSO", "SEM CABEÇA", "M6", "0.75", "12", "45H"),
        ("DIN985", "PORCA", "SEXTAVADA AUTOTRAVANTE", "M10", "1.5", None, "10"),
        ("ISO7089", "ARRUELA", "LISA", "8", None, None, "200HV"),
        ("DIN976-1", "BARRA ROSCADA", "COM ROSCA TOTAL", "M12", "1.75", "1000", "10.9"),
    ],
)
def test_portuguese_fastener_engineering_tokens(norm, kind, family, diameter, pitch, length, grade):
    import copy

    from forgepdm.domain.description_generation import generate

    geometry = {"Type": norm, "Diameter": diameter}
    if pitch:
        geometry["PitchCustom"] = pitch
    if length:
        geometry["Length"] = length
    spec = fastener_spec(norm, geometry=geometry, grade=grade)
    before = copy.deepcopy(spec)
    dimensions = "X".join(t for t in (diameter, pitch, length) if t)
    assert generate(spec, "pt-BR")["text"] == (
        f"{kind} AÇO {family} {norm} {dimensions} {grade} SEM REVESTIMENTO"
    )
    assert spec == before


@pytest.mark.parametrize(
    "norm,expected,forbidden",
    [
        ("DIN980", "SEXTAVADA AUTOTRAVANTE", "NYLON"),
        ("ISO7042", "SEXTAVADA AUTOTRAVANTE", "NYLON"),
        ("DIN985", "SEXTAVADA AUTOTRAVANTE", "NYLON"),
        ("ISO7040", "SEXTAVADA AUTOTRAVANTE", "NYLON"),
        ("DIN913", "SEM CABEÇA", "PONTA CÔNICA"),
        ("DIN914", "SEM CABEÇA", "PONTA PLANA"),
        ("DIN915", "SEM CABEÇA", "PONTA CÔNCAVA"),
        ("DIN916", "SEM CABEÇA", "PONTA PLANA"),
        ("ISO4766", "SEM CABEÇA", "SEXTAVADO INTERNO"),
        ("ISO14579", "CABEÇA CILÍNDRICA COM ENCAIXE INTERNO", "SEXTAVADO INTERNO"),
        ("DIN6923", "SEXTAVADA COM FLANGE", "SERRILHADA"),
        ("ISO4162", "CABEÇA SEXTAVADA COM FLANGE", "SERRILHADA"),
        ("ISO7380-1", "CABEÇA ABAULADA", "COM FLANGE"),
        ("DIN137", "ELÁSTICA", "HELICOIDAL"),
    ],
)
def test_portuguese_families_do_not_invent_standard_details(norm, expected, forbidden):
    from forgepdm.domain.description_generation import generate

    text = generate(fastener_spec(norm), "pt-BR")["text"]
    assert expected in text
    assert forbidden not in text


@pytest.mark.parametrize("field,section", [("material", "materials"), ("finish", "finishes")])
def test_all_current_fastener_options_have_local_terms(field, section, monkeypatch):
    from forgepdm.domain.description_generation import generate

    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "clients/freecad"))
    from freecad.forgepdm.standard_options import FINISHES, MATERIALS

    options = MATERIALS if field == "material" else FINISHES
    for option in options:
        if option["value"] is None:
            continue
        value = option["value"]
        assert value.upper() in PT_BR_TERMS[section], value
        proposal = generate(fastener_spec(**{field: value}), "pt-BR")
        assert not proposal["warnings"], value
        assert PT_BR_TERMS[section][value.upper()] in proposal["text"]


@pytest.mark.parametrize(
    "field,raw",
    [("material", "Unlisted Alloy Cu-X"), ("finish", "zinc plated Mystery™")],
)
def test_unknown_fastener_vocabulary_retains_original_and_warns(field, raw):
    from forgepdm.domain.description_generation import generate

    proposal = generate(fastener_spec(**{field: raw}), "pt-BR")
    assert raw in proposal["text"]
    assert any(raw in warning for warning in proposal["warnings"])
    assert proposal["provenance"]["warnings"] == proposal["warnings"]
    assert proposal["state"] == "draft"


@pytest.mark.parametrize("field", ["material", "finish"])
def test_missing_fastener_vocabulary_entry_is_explicit(field, tmp_path, monkeypatch):
    from forgepdm.domain import description_generation as generation

    vocabulary = json.loads(json.dumps(PT_BR_TERMS))
    section, key, raw = (
        ("materials", "STEEL", "steel") if field == "material" else ("finishes", "PLAIN", "plain")
    )
    del vocabulary[section][key]
    path = tmp_path / "pt-BR.json"
    path.write_text(json.dumps(vocabulary), encoding="utf-8")
    monkeypatch.setitem(generation.VOCABULARIES, "pt-BR", str(path))
    proposal = generation.generate(fastener_spec(), "pt-BR")
    assert raw in proposal["text"]
    assert proposal["warnings"] == [f"{section}: {raw}"]


@pytest.mark.parametrize("field", ["material", "grade", "finish"])
def test_unspecified_fastener_property_is_not_plain_or_not_applicable(field):
    from forgepdm.domain.description_generation import generate

    proposal = generate(fastener_spec(**{field: None}), "pt-BR")
    assert "NÃO ESPECIFICADO" in proposal["text"]
    assert proposal["warnings"] == [f"{field}: unspecified property"]


@pytest.mark.parametrize("locale", ["pt-BR", "en"])
def test_unknown_fastener_standard_requires_manual_translation(locale):
    from forgepdm.domain.description_generation import generate

    with pytest.raises(ValueError, match="unknown standard; enter a manual translation"):
        generate(fastener_spec("UNLISTED123"), locale)


def test_portuguese_custom_dimensions_descriptors_and_not_applicable():
    from forgepdm.domain.description_generation import generate

    spec = fastener_spec(
        geometry={
            "Type": "ISO4017",
            "Diameter": "custom",
            "DiameterCustom": "8.5",
            "PitchCustom": "1.25",
            "Length": "custom",
            "LengthCustom": "25.5",
            "LeftHanded": True,
            "Blind": True,
            "Width": "10",
            "ScrewLength": "15",
            "SlotWidth": "2",
            "ExternalDiam": "20",
            "KeySize": "4",
            "Tcode": "30",
        },
        grade="not applicable",
    )
    proposal = generate(spec, "pt-BR")
    assert (
        "M8.5X1.25X25.5 W10 SL15 SW2 OD20 K4 T30 ROSCA À ESQUERDA CEGO NÃO APLICÁVEL"
        in proposal["text"]
    )
    assert not proposal["warnings"]
    assert "BLIND" not in proposal["text"]
    spec["geometry"].update(Blind=False, LeftHanded=False)
    text = generate(spec, "pt-BR")["text"]
    assert "CEGO" not in text and "ROSCA À ESQUERDA" not in text


def test_portuguese_unknown_descriptor_and_missing_dimension_warn():
    from forgepdm.domain.description_generation import generate

    proposal = generate(fastener_spec(geometry={"Type": "ISO4017", "Blind": "Unknown"}), "pt-BR")
    assert "DIMENSÃO NÃO ESPECIFICADA" in proposal["text"]
    assert "Blind=Unknown" in proposal["text"]
    assert proposal["warnings"] == ["Diameter: unspecified property", "Blind: Unknown"]


@pytest.mark.parametrize("norm,pair", FASTENER_NORMS.items(), ids=FASTENER_NORMS)
def test_every_english_fastener_proposal_retains_catalog_contract(norm, pair, monkeypatch):
    from forgepdm.domain.description_generation import generate

    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "clients/freecad"))
    from freecad.forgepdm.standard_options import NORMS, catalog_text

    assert list(NORMS[norm]) == pair
    for purchasing in [
        {},
        {"material": None, "grade": None, "finish": None},
        {"material": "Special Alloy", "finish": "Custom Finish"},
    ]:
        spec = fastener_spec(norm, **purchasing)
        spec["geometry"].update(Blind=True, LeftHanded=True, Width="10")
        assert generate(spec, "en")["text"] == catalog_text(spec, *pair)[0]


def test_fastener_vocabulary_upgrade_keeps_approved_text_until_explicit_approval(
    backend, tmp_path, monkeypatch
):
    from test_standard_parts import register

    from forgepdm.domain import description_generation as generation

    b = backend
    item = register(b, fastener_spec(), source_language="en")
    svc = LocalizationService(b.database, b.authorization)
    user = b.users["editor"]
    s = source(svc, b, item)
    draft = svc.change(user, s["id"], "generate", s["token"], "pt-BR")
    saved = draft["translations"][-1]
    provenance = json.loads(saved["provenance_json"])
    assert provenance["vocabulary_version"] == PT_BR_TERMS["version"]
    assert provenance["version"] == 1  # The shared standard map is unchanged.
    # Existing stored proposals predate the separate vocabulary metadata.
    legacy_provenance = {k: v for k, v in provenance.items() if not k.startswith("vocabulary_")}
    with b.database.transaction() as c:
        c.execute(
            "UPDATE localized_translation_versions SET provenance_json=? WHERE id=?",
            (json.dumps(legacy_provenance), saved["id"]),
        )
    draft = source(svc, b, item)
    with b.database.connection() as c:
        assert resolve(c, item.id, None, "designation", "pt-BR")["text"] == "Bolt"
    approved = svc.change(user, s["id"], "approve", draft["token"], translation_id=saved["id"])
    vocabulary = json.loads(json.dumps(PT_BR_TERMS))
    vocabulary["version"] += 1
    vocabulary["families"]["HEX HEAD"] = "CABEÇA HEXAGONAL"
    path = tmp_path / "pt-BR.json"
    path.write_text(json.dumps(vocabulary), encoding="utf-8")
    monkeypatch.setitem(generation.VOCABULARIES, "pt-BR", str(path))
    updated = svc.change(user, s["id"], "generate", approved["token"], "pt-BR")
    newer = next(t for t in updated["translations"] if t["state"] == "draft")
    assert "CABEÇA HEXAGONAL" in newer["text"]
    assert json.loads(newer["provenance_json"])["vocabulary_version"] == vocabulary["version"]
    with b.database.connection() as c:
        assert resolve(c, item.id, None, "designation", "pt-BR")["text"] == saved["text"]
    svc.change(user, s["id"], "approve", updated["token"], translation_id=newer["id"])
    with b.database.connection() as c:
        assert resolve(c, item.id, None, "designation", "pt-BR")["text"] == newer["text"]
        assert (
            json.loads(
                c.execute(
                    "SELECT provenance_json FROM localized_translation_versions WHERE id=?",
                    (saved["id"],),
                ).fetchone()[0]
            )
            == legacy_provenance
        )
        assert c.execute(
            "SELECT specification_json FROM standard_specifications WHERE item_id=?", (item.id,)
        ).fetchone()[0] == json.dumps(
            specification(fastener_spec()), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
