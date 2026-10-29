"""Verify the preserved client request contract without a backend dependency."""

import importlib.util
import io
import json

import pytest


@pytest.fixture
def api(addon_root):
    spec = importlib.util.spec_from_file_location(
        "client_api", addon_root / "freecad/forgepdm/api.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("method", "arguments", "verb", "path", "payload"),
    [
        (
            "create_item",
            ("part", "Bracket", "project"),
            "POST",
            "/api/v1/items",
            {"kind": "part", "name": "Bracket", "description": "", "project_id": "project"},
        ),
        ("get_item", ("item",), "GET", "/api/v1/items/item", None),
        ("get_bom", ("rev", True), "GET", "/api/v1/revisions/rev/bom?recursive=true", None),
        ("list_datasets", ("rev",), "GET", "/api/v1/revisions/rev/datasets", None),
        (
            "checkin",
            ("rev", "note"),
            "POST",
            "/api/v1/revisions/rev/checkin",
            {"change_note": "note"},
        ),
        (
            "transition",
            ("rev", "released"),
            "POST",
            "/api/v1/revisions/rev/lifecycle",
            {"target": "released"},
        ),
        (
            "create_next_revision",
            ("item", "note"),
            "POST",
            "/api/v1/items/item/revisions",
            {"change_note": "note"},
        ),
        ("acquire_checkout", ("rev",), "POST", "/api/v1/revisions/rev/checkout", None),
        ("renew_checkout", ("rev",), "POST", "/api/v1/revisions/rev/checkout/renew", None),
    ],
)
def test_json_contract(api, monkeypatch, method, arguments, verb, path, payload):
    client = api.ForgePDMClient("http://localhost:8000")
    calls = []

    def request(verb, path, payload=None):
        calls.append((verb, path, payload))
        return {"ok": True}

    monkeypatch.setattr(client, "_json_request", request)
    assert getattr(client, method)(*arguments) == {"ok": True}
    assert calls == [(verb, path, payload)]


def test_login_bearer_and_logout_contract(api, monkeypatch):
    requests = []

    class Response(io.BytesIO):
        status = 200

    def urlopen(request, timeout):
        requests.append(request)
        if request.full_url.endswith("/auth/login"):
            return Response(json.dumps({"access_token": "secret", "user": {"id": "user"}}).encode())
        return Response(b"")

    monkeypatch.setattr(api.urllib.request, "urlopen", urlopen)
    client = api.ForgePDMClient("https://example.invalid/pdm")
    assert client.login("alice", "password") == {"id": "user"}
    assert json.loads(requests[0].data) == {"username": "alice", "password": "password"}
    assert requests[0].full_url == "https://example.invalid/pdm/api/v1/auth/login"
    assert requests[0].get_header("Authorization") is None
    client.logout()
    assert requests[1].get_header("Authorization") == "Bearer secret"
    assert requests[1].get_method() == "POST"
    assert requests[1].full_url.endswith("/api/v1/auth/logout")
    assert client.token is None


def test_streamed_upload_contract(api, monkeypatch, tmp_path):
    calls, chunks = [], []

    class Connection:
        def putrequest(self, *args):
            calls.append(args)

        def putheader(self, *args):
            calls.append(args)

        def endheaders(self):
            pass

        def send(self, data):
            chunks.append(data)

        def getresponse(self):
            return type("Response", (), {"status": 201, "read": lambda self: b'{"id":"dataset"}'})()

        def close(self):
            calls.append(("closed",))

    client = api.ForgePDMClient("https://example.invalid/pdm")
    client.token = "secret"
    monkeypatch.setattr(client, "_http_connection", Connection)
    file = tmp_path / "part.FCStd"
    file.write_bytes(b"CAD-content")
    assert client.upload_file("rev", str(file), name="Native CAD") == {"id": "dataset"}
    assert ("POST", "/pdm/api/v1/revisions/rev/datasets") in calls
    assert ("Authorization", "Bearer secret") in calls
    body = b"".join(chunks)
    assert b'name="dataset_type"\r\n\r\nnative_cad' in body
    assert b'name="name"\r\n\r\nNative CAD' in body
    assert b'filename="part.FCStd"' in body and b"CAD-content" in body
    assert ("Content-Length", str(len(body))) in calls
    assert calls[-1] == ("closed",)


def test_download_contract(api, monkeypatch, tmp_path):
    requests = []

    def urlopen(request, timeout):
        requests.append(request)
        return io.BytesIO(b"CAD-content")

    monkeypatch.setattr(api.urllib.request, "urlopen", urlopen)
    client = api.ForgePDMClient("https://example.invalid/pdm")
    client.token = "secret"
    destination = tmp_path / "part.FCStd"
    assert client.download_file("file", str(destination)) == str(destination)
    assert destination.read_bytes() == b"CAD-content"
    assert requests[0].full_url == "https://example.invalid/pdm/api/v1/files/file"
    assert requests[0].get_header("Authorization") == "Bearer secret"
    assert not (tmp_path / "part.FCStd.part").exists()


def test_uuid_validation_error_has_readable_guidance(api):
    body = json.dumps(
        {
            "detail": [
                {
                    "type": "uuid_parsing",
                    "loc": ["body", "project_id"],
                    "msg": "Input should be a valid UUID, invalid length: found 6",
                    "input": "241205",
                    "ctx": {"error": "invalid length: found 6"},
                }
            ]
        }
    ).encode()
    with pytest.raises(api.ForgePDMError) as caught:
        api.ForgePDMClient._decode_response(422, body)
    assert caught.value.status == 422
    assert "not its project number" in str(caught.value)
    assert "uuid_parsing" not in str(caught.value)
    assert "'loc'" not in str(caught.value)
    assert "241205" not in str(caught.value)


@pytest.mark.parametrize(
    ("detail", "expected"),
    [
        ([{"loc": ["body", "name"], "msg": "Field required"}], "Name: Field required"),
        ("project editor access is required", "project editor access is required"),
        ({"unexpected": "value"}, "ForgePDM request failed (HTTP 422)."),
        ([], "ForgePDM request failed (HTTP 422)."),
    ],
)
def test_other_api_errors_remain_readable(api, detail, expected):
    with pytest.raises(api.ForgePDMError) as caught:
        api.ForgePDMClient._decode_response(422, json.dumps({"detail": detail}).encode())
    assert expected in str(caught.value)
