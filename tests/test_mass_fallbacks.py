"""S mass fallbacks preserve source priority, revision rules and explicit unknowns."""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from test_reference_mass import SPEC, create_standard, evidence, service

from forgepdm.domain.entities import Conflict, Forbidden, ItemKind, LifecycleState
from forgepdm.domain.reference_mass import density_reference, estimate_mass


def estimate(svc, b, item, **changes):
    return {
        "method": "cad_estimate",
        "expected_token": svc.read(b.users["editor"], item.current_revision_id)["token"],
        "geometry": SPEC["geometry"],
        "volume_mm3": "1000",
        "shape_sha256": "a" * 64,
        "thread_mode": "simplified",
        "generator_version": "0.5.43",
        **changes,
    }


def manual(svc, b, item, **changes):
    return {
        "method": "manual",
        "expected_token": svc.read(b.users["editor"], item.current_revision_id)["token"],
        "mass_g": "8.5",
        "note": "Measured sample",
        **changes,
    }


def test_estimate_and_manual_are_distinct_provenance_and_concurrency(backend):
    b = backend
    item = create_standard(b)
    svc = service(b)
    old = estimate(svc, b, item)
    value = svc.save_fallback(b.users["editor"], item.current_revision_id, old)
    assert value["status"] == "cad_estimate" and Decimal(value["mass_kg"]) == Decimal("0.0079")
    assert (
        value["density_reference"]["name"] == "Steel-Generic"
        and value["thread_mode"] == "simplified"
    )
    with pytest.raises(Conflict):
        svc.save_fallback(b.users["editor"], item.current_revision_id, old)
    updated = svc.save_fallback(b.users["editor"], item.current_revision_id, manual(svc, b, item))
    assert updated["status"] == "manual" and updated["mass_kg"] == "0.0085"
    assert updated["note"] == "Measured sample"
    assert (
        svc.save_fallback(b.users["editor"], item.current_revision_id, estimate(svc, b, item))
        == updated
    )
    with b.database.connection() as c:
        assert (
            c.execute(
                "SELECT count(*) FROM audit_events WHERE event_type='standard.fallback_mass_saved'"
            ).fetchone()[0]
            == 2
        )


def test_supplier_wins_and_manual_is_not_automatically_replaced(backend):
    b = backend
    item = create_standard(b)
    provider = SimpleNamespace(lookup=lambda spec: evidence())
    svc = service(b, provider)
    svc.save_fallback(b.users["editor"], item.current_revision_id, estimate(svc, b, item))
    supplier = svc.lookup(b.users["editor"], item.current_revision_id)
    assert supplier["status"] == "supplier_reference" and supplier["mass_kg"] == "0.016"
    with pytest.raises(Conflict, match="supplier"):
        svc.save_fallback(b.users["editor"], item.current_revision_id, manual(svc, b, item))
    other = b.items.create_item(
        kind=ItemKind.PART,
        number_series="S",
        name="Other",
        description="",
        created_by=b.users["editor"].id,
    )
    saved = svc.save_fallback(b.users["editor"], other.current_revision_id, manual(svc, b, other))
    assert svc.read(b.users["viewer"], other.current_revision_id) == saved
    assert svc.lookup(b.users["editor"], other.current_revision_id) == saved


def test_unknown_material_has_no_density_and_manual_still_works(backend):
    b = backend
    item = b.items.create_item(
        kind=ItemKind.PART,
        number_series="S",
        name="Unknown",
        description="",
        created_by=b.users["editor"].id,
        standard_specification={**SPEC, "material": None},
    )
    svc = service(b)
    assert svc.read(b.users["editor"], item.current_revision_id)["estimate_context"] is None
    with pytest.raises(ValueError, match="density"):
        svc.save_fallback(b.users["editor"], item.current_revision_id, estimate(svc, b, item))
    assert svc.read(b.users["editor"], item.current_revision_id)["mass_kg"] is None
    assert (
        svc.save_fallback(b.users["editor"], item.current_revision_id, manual(svc, b, item))[
            "status"
        ]
        == "manual"
    )


def test_release_checkout_permissions_and_copy(backend):
    b = backend
    item = create_standard(b)
    svc = service(b)
    payload = manual(svc, b, item)
    with pytest.raises(Forbidden):
        svc.save_fallback(b.users["viewer"], item.current_revision_id, payload)
    with pytest.raises(Conflict):
        svc.save_fallback(b.users["admin"], item.current_revision_id, payload)
    saved = svc.save_fallback(b.users["editor"], item.current_revision_id, payload)
    b.revisions.check_in(b.users["editor"], item.current_revision_id)
    b.revisions.transition_lifecycle(
        b.users["editor"], item.current_revision_id, LifecycleState.RELEASED
    )
    with pytest.raises(Conflict):
        svc.save_fallback(b.users["editor"], item.current_revision_id, manual(svc, b, item))
    revision, _ = b.revisions.create_next_revision(b.users["editor"], item.id, "Update mass")
    assert svc.read(b.users["editor"], revision.id) == saved
    assert svc.read(b.users["editor"], item.current_revision_id) == saved


@pytest.mark.parametrize(
    "changes",
    [
        {"volume_mm3": "0"},
        {"volume_mm3": "NaN"},
        {"volume_mm3": "-1"},
        {"volume_mm3": "1e200"},
        {"shape_sha256": "bad"},
        {"geometry": {**SPEC["geometry"], "Length": "35"}},
        {"thread_mode": "guess"},
        {"generator_version": ""},
    ],
)
def test_rejects_bad_estimates_atomically(backend, changes):
    b = backend
    item = create_standard(b)
    svc = service(b)
    with pytest.raises((ValueError, Conflict)):
        svc.save_fallback(
            b.users["editor"], item.current_revision_id, estimate(svc, b, item, **changes)
        )
    assert svc.read(b.users["editor"], item.current_revision_id)["mass_kg"] is None


@pytest.mark.parametrize("value", ["0", "-1", "NaN", "Infinity", "1e1000", "abc"])
def test_rejects_bad_manual_values(backend, value):
    b = backend
    item = create_standard(b)
    svc = service(b)
    with pytest.raises(ValueError):
        svc.save_fallback(
            b.users["editor"], item.current_revision_id, manual(svc, b, item, mass_g=value)
        )
    assert svc.read(b.users["editor"], item.current_revision_id)["mass_kg"] is None


def test_density_surrogates_are_explicit_not_unknown_guesses():
    assert density_reference({**SPEC, "material": "carbon steel"})["density_kg_m3"] == "7800"
    for material in (None, "unknown", "aço carbono", "titanium", "stainless steel"):
        assert density_reference({**SPEC, "material": material}) is None
    assert estimate_mass("1000", "7900") == "0.0079"


def test_fallback_api_and_stale_manual_edit(backend):
    from fastapi.testclient import TestClient

    from forgepdm.api.v1.routes import current_user
    from forgepdm.main import create_app

    b = backend
    item = create_standard(b)
    app = create_app(b.database.path)
    app.dependency_overrides[current_user] = lambda: b.users["editor"]
    path = "/api/v1/revisions/" + item.current_revision_id + "/reference-mass"
    with TestClient(app) as client:
        value = client.get(path).json()
        assert value["estimate_context"]["density_reference"]["density_kg_m3"] == "7900"
        request = {"method": "manual", "mass_g": "12.25", "expected_token": value["token"]}
        saved = client.put(path + "/fallback", json=request)
        assert saved.status_code == 200 and saved.json()["mass_kg"] == "0.01225"
        assert client.put(path + "/fallback", json=request).status_code == 409
        bad = {**request, "expected_token": saved.json()["token"], "mass_g": "NaN"}
        assert client.put(path + "/fallback", json=bad).status_code == 422
        app.dependency_overrides[current_user] = lambda: b.users["viewer"]
        assert client.put(path + "/fallback", json={**bad, "mass_g": "5"}).status_code == 403


def test_concurrent_manual_entry_wins_over_inflight_supplier_upgrade(backend):
    b = backend
    item = create_standard(b)
    svc = service(b)
    svc.save_fallback(b.users["editor"], item.current_revision_id, estimate(svc, b, item))

    def racing(spec):
        svc.save_fallback(b.users["editor"], item.current_revision_id, manual(svc, b, item))
        return evidence()

    svc.provider = SimpleNamespace(lookup=racing)
    value = svc.lookup(b.users["editor"], item.current_revision_id)
    assert value["status"] == "manual" and value["mass_kg"] == "0.0085"
    assert svc.read(b.users["editor"], item.current_revision_id) == value


def test_readers_reuse_estimates_without_network_and_released_is_immutable(backend):
    b = backend
    item = create_standard(b)
    calls = []
    svc = service(b, SimpleNamespace(lookup=lambda spec: calls.append(1) or evidence()))
    saved = svc.save_fallback(b.users["editor"], item.current_revision_id, estimate(svc, b, item))
    assert svc.lookup(b.users["viewer"], item.current_revision_id) == saved
    b.revisions.check_in(b.users["editor"], item.current_revision_id)
    b.revisions.transition_lifecycle(
        b.users["editor"], item.current_revision_id, LifecycleState.RELEASED
    )
    assert svc.lookup(b.users["editor"], item.current_revision_id) == saved
    assert calls == []
