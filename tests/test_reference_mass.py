"""Supplier mass lookup is exact, revision-bound, optional and independently testable."""

import csv
import io
import json
from types import SimpleNamespace

import pytest

from forgepdm.application.reference_mass import CSV_FIELDS, ReferenceMassService
from forgepdm.domain.entities import Conflict, Forbidden, ItemKind, LifecycleState
from forgepdm.domain.reference_mass import mass_kg, specification_key
from forgepdm.domain.standard_parts import specification
from forgepdm.infrastructure.fabory import FaboryProvider, candidate_url, parse_product

SPEC = specification(
    {
        "geometry": {"Type": "ISO4762", "Diameter": "M8", "Length": "30", "LeftHanded": False},
        "material": "steel",
        "grade": "10.9",
        "finish": "plain",
    }
)


def evidence():
    return {
        "supplier": "Fabory",
        "source_article": "07015.080.030",
        "source_url": candidate_url(SPEC),
        "source_mass": "16",
        "source_unit": "g",
        "source_quantity": "1",
        "mass_kg": "0.016",
    }


def page(changes=None):
    rows = {
        "ISO": "4762",
        "DIN": "912",
        "Diameter": "M8",
        "Length": "30 mm",
        "Thread direction": "Right",
        "Thread": "Metric thread",
        "Material": "Steel",
        "Class": "10.9",
        "Surface treatment": "Plain",
        "Article number": "07015.080.030",
        "Weight per piece (g)": "16",
    }
    rows.update(changes or {})
    return (
        "<table>"
        + "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in rows.items())
        + "</table>"
    ).encode()


def service(b, provider=None):
    return ReferenceMassService(b.database, b.authorization, b.revisions, provider)


def create_standard(b):
    return b.items.create_item(
        kind=ItemKind.PART,
        number_series="S",
        name="Test screw",
        description="",
        created_by=b.users["editor"].id,
        standard_specification=SPEC,
    )


def csv_feed(rows=None):
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=sorted(CSV_FIELDS))
    writer.writeheader()
    row = {
        "specification_json": json.dumps(SPEC),
        "supplier": "Supplier",
        "source_article": "ABC",
        "source_url": "https://example.com/product/ABC",
        "mass": "1.6",
        "unit": "kg",
        "quantity": "100",
    }
    writer.writerows(rows or [row])
    return stream.getvalue()


@pytest.mark.parametrize(
    "value,unit,count,expected",
    [("16", "g", 1, "0.016"), ("1.6", "kg", 100, "0.016"), ("16", "kg", 1000, "0.016")],
)
def test_normalizes_unit_and_piece_count(value, unit, count, expected):
    assert mass_kg(value, unit, count) == expected


@pytest.mark.parametrize(
    "value,unit,count",
    [
        ("NaN", "g", 1),
        ("1", "lb", 1),
        ("0", "kg", 100),
        ("2", "kg", 0),
        ("Infinity", "g", 1),
        ("1", "g", "NaN"),
    ],
)
def test_rejects_invalid_quantities(value, unit, count):
    with pytest.raises(ValueError):
        mass_kg(value, unit, count)


def test_fabory_checks_entire_spec_and_never_uses_unverified_values():
    url = candidate_url(SPEC)
    assert parse_product(page(), url, SPEC)["mass_kg"] == "0.016"
    for change in (
        {"Class": "8.8"},
        {"Material": "Stainless steel"},
        {"Diameter": "M10"},
        {"Length": "35 mm"},
        {"Thread direction": "Left"},
        {"Surface treatment": "Zinc plated"},
        {"Weight per piece (g)": ""},
        {"ISO": "4017"},
        {"Article number": "different"},
    ):
        assert parse_product(page(change), url, SPEC) is None
    assert parse_product(page() + b"<tr><th>Class</th><td>8.8</td></tr>", url, SPEC) is None
    assert parse_product(page(), "https://evil.example/product", SPEC) is None
    for geometry in ({"PitchCustom": "1.5"}, {"LeftHanded": "true"}, {"Diameter": "M8.5"}):
        assert candidate_url({**SPEC, "geometry": {**SPEC["geometry"], **geometry}}) is None
    assert candidate_url({**SPEC, "material": None}) is None


def test_robots_policy_and_no_search_crawling():
    calls = []

    def fetch(url):
        calls.append(url)
        return b"User-agent: *\nDisallow: /\n" if url.endswith("robots.txt") else page()

    assert FaboryProvider(fetch).lookup(SPEC) is None
    assert len(calls) == 1
    calls = []

    def allowed(url):
        calls.append(url)
        return b"User-agent: *\nDisallow: /*/search*\n" if url.endswith("robots.txt") else page()

    assert FaboryProvider(allowed).lookup(SPEC)["mass_kg"] == "0.016"
    assert len(calls) == 2 and not any("search" in u for u in calls)


def test_lookup_once_provenance_revisions_and_reader_reuse(backend):
    b = backend
    item = create_standard(b)
    calls = []
    svc = service(b, SimpleNamespace(lookup=lambda spec: calls.append(spec) or evidence()))
    saved = svc.lookup(b.users["editor"], item.current_revision_id)
    assert saved["specification_key"] == specification_key(SPEC)
    assert saved["status"] == "supplier_reference" and saved["retrieved_at"]
    assert svc.lookup(b.users["viewer"], item.current_revision_id) == saved and len(calls) == 1
    b.revisions.check_in(b.users["editor"], item.current_revision_id)
    b.revisions.transition_lifecycle(
        b.users["editor"], item.current_revision_id, LifecycleState.RELEASED
    )
    revision, _ = b.revisions.create_next_revision(b.users["editor"], item.id, "Next")
    assert svc.read(b.users["editor"], revision.id) == saved
    assert svc.read(b.users["editor"], item.current_revision_id) == saved


def test_network_failure_is_optional_and_attempts_are_bounded(backend):
    b = backend
    item = create_standard(b)
    calls = []

    def fail(spec):
        calls.append(1)
        raise TimeoutError()

    svc = service(b, SimpleNamespace(lookup=fail))
    assert svc.lookup(b.users["editor"], item.current_revision_id)["mass_kg"] is None
    assert svc.lookup(b.users["editor"], item.current_revision_id)["mass_kg"] is None
    assert len(calls) == 1


def test_csv_import_atomic_exact_and_admin_only(backend):
    b = backend
    svc = service(b)
    item = create_standard(b)
    with pytest.raises(Forbidden):
        svc.import_csv(b.users["viewer"], csv_feed())
    assert svc.import_csv(b.users["admin"], csv_feed()) == {"imported": 1}
    assert svc.lookup(b.users["editor"], item.current_revision_id)["mass_kg"] == "0.016"
    for text in (
        csv_feed() + csv_feed().split("\n", 1)[1],
        csv_feed().replace("https://example.com", "http://example.com"),
    ):
        with pytest.raises(ValueError):
            svc.import_csv(b.users["admin"], text)
    assert svc.read(b.users["viewer"], item.current_revision_id)["mass_kg"] == "0.016"


def test_no_write_to_released_or_other_users_checkout(backend):
    b = backend
    item = create_standard(b)
    calls = []
    svc = service(b, SimpleNamespace(lookup=lambda spec: calls.append(1) or evidence()))
    assert svc.lookup(b.users["editor2"], item.current_revision_id)["mass_kg"] is None
    b.revisions.check_in(b.users["editor"], item.current_revision_id)
    b.revisions.transition_lifecycle(
        b.users["editor"], item.current_revision_id, LifecycleState.RELEASED
    )
    assert svc.lookup(b.users["editor"], item.current_revision_id)["mass_kg"] is None
    assert not calls


def test_checkout_loss_during_network_lookup_does_not_write(backend):
    b = backend
    item = create_standard(b)

    def racing(spec):
        b.revisions.check_in(b.users["editor"], item.current_revision_id)
        return evidence()

    svc = service(b, SimpleNamespace(lookup=racing))
    with pytest.raises(Conflict):
        svc.lookup(b.users["editor"], item.current_revision_id)
    assert svc.read(b.users["editor"], item.current_revision_id)["mass_kg"] is None


def test_api_registration_enriches_without_new_fields_and_preserves_on_failure(
    backend, monkeypatch
):
    from fastapi.testclient import TestClient

    from forgepdm.api.v1.routes import current_user
    from forgepdm.main import create_app

    b = backend
    app = create_app(b.database.path)
    calls = []
    app.state.reference_mass_service.provider = SimpleNamespace(
        lookup=lambda spec: calls.append(spec) or evidence()
    )
    with TestClient(app) as client:
        assert (
            client.get(
                "/api/v1/revisions/00000000-0000-0000-0000-000000000000/reference-mass"
            ).status_code
            == 401
        )
        app.dependency_overrides[current_user] = lambda: b.users["editor"]
        payload = {
            "kind": "part",
            "number_series": "S",
            "name": "API screw",
            "standard_specification": SPEC,
        }
        response = client.post("/api/v1/items", json=payload)
        assert response.status_code == 201, response.text
        item = response.json()
        revision = item["current_revision_id"]
        assert item["reference_mass"]["mass_kg"] == "0.016" and len(calls) == 1
        assert (
            client.get(f"/api/v1/revisions/{revision}/reference-mass").json()["source_article"]
            == "07015.080.030"
        )
        assert (
            client.post(f"/api/v1/revisions/{revision}/reference-mass/lookup").json()["mass_kg"]
            == "0.016"
        )
        assert len(calls) == 1
        app.dependency_overrides[current_user] = lambda: b.users["viewer"]
        assert (
            client.post(
                "/api/v1/reference-masses/import", json={"csv_text": csv_feed()}
            ).status_code
            == 403
        )
        app.dependency_overrides[current_user] = lambda: b.users["admin"]
        assert client.post(
            "/api/v1/reference-masses/import", json={"csv_text": csv_feed()}
        ).json() == {"imported": 1}
        app.dependency_overrides[current_user] = lambda: b.users["editor"]
        app.state.reference_mass_service.lookup = lambda *args: (_ for _ in ()).throw(
            RuntimeError("unavailable")
        )
        response = client.post(
            "/api/v1/items",
            json={
                **payload,
                "name": "Another",
                "standard_specification": {
                    **SPEC,
                    "geometry": {**SPEC["geometry"], "Length": "35"},
                },
            },
        )
        assert response.status_code == 201 and response.json()["reference_mass"]["mass_kg"] is None
