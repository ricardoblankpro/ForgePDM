"""Proposal availability is permission checked and must never persist a draft."""

import pytest
from conftest import create_item

from forgepdm.application.localization import LocalizationService


def canonical(b, item):
    svc = LocalizationService(b.database, b.authorization)
    source = next(
        s
        for s in svc.list(b.users["editor"], item.id, item.current_revision_id)
        if s["field"] == "description"
    )
    return svc, source


def test_unsupported_and_read_only_sources_hide_assistance(backend):
    b = backend
    item = create_item(b, kind="assembly")
    svc, s = canonical(b, item)
    assert svc.proposal_availability(b.users["editor"], s["id"], "en") == {"available": False}
    assert svc.proposal_availability(b.users["viewer"], s["id"], "en") == {"available": False}
    with pytest.raises(ValueError):
        svc.proposal_availability(b.users["editor"], s["id"], "unknown")


def test_structured_availability_is_read_only_and_uses_existing_generator(backend):
    from test_standard_parts import register

    b = backend
    item = register(b, source_language="en")
    svc, s = canonical(b, item)
    result = svc.proposal_availability(b.users["editor"], s["id"], "pt-BR")
    assert result["available"] and result["label"] == "Generate from specification"
    assert (
        next(
            t
            for t in svc.list(b.users["editor"], item.id, item.current_revision_id)
            if t["id"] == s["id"]
        )
        == s
    )
    assert svc.proposal_availability(b.users["editor"], s["id"], "en") == {"available": False}


def test_material_assistance_requires_matching_authorized_approved_text(backend):
    from test_descriptions import material, service

    b = backend
    m = material(b)
    p = create_item(b)
    desc = service(b)
    user = b.users["editor"]
    desc.save(
        user,
        p.current_revision_id,
        "",
        m.current_revision_id,
        desc.read(user, p.current_revision_id)["token"],
    )
    svc, source = canonical(b, p)
    assert not svc.proposal_availability(user, source["id"], "en")["available"]
    ms = canonical(b, m)[1]
    ms = svc.change(user, ms["id"], "correct-language", ms["token"], "pt-BR")
    ms = svc.change(user, ms["id"], "draft", ms["token"], "en", "Steel plate")
    assert not svc.proposal_availability(user, source["id"], "en")["available"]
    svc.change(user, ms["id"], "approve", ms["token"], translation_id=ms["translations"][-1]["id"])
    assert svc.proposal_availability(user, source["id"], "en") == {
        "available": True,
        "label": "Use material translation",
        "warnings": [],
    }
    assert canonical(b, p)[1]["translations"] == []


def test_availability_api_requires_authentication_and_source_read_access(backend, monkeypatch):
    from fastapi.testclient import TestClient

    from forgepdm.api.v1.routes import current_user
    from forgepdm.main import create_app

    b = backend
    item = create_item(b, kind="assembly")
    _, source = canonical(b, item)
    monkeypatch.setenv("FORGEPDM_FILE_ROOT", str(b.storage.root))
    app = create_app(b.database.path)
    path = f"/api/v1/localized-texts/{source['id']}/proposal-availability?language=en"
    with TestClient(app) as client:
        assert client.get(path).status_code == 401
        app.dependency_overrides[current_user] = lambda: b.users["viewer"]
        assert client.get(path).json() == {"available": False}
        with b.database.transaction() as c:
            c.execute(
                "DELETE FROM project_memberships WHERE user_id=? AND project_id=?",
                (b.users["viewer"].id, b.project_id),
            )
        assert client.get(path).status_code == 403
