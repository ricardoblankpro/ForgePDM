"""Transport cancellation, timeout, session expiry and settings boundaries."""

from datetime import datetime, timedelta, timezone
import importlib.util
import io
import sys
from types import SimpleNamespace

import pytest

from freecad.forgepdm.jobs import Context, OperationCancelled
from freecad.forgepdm.session import Session


@pytest.fixture
def api(addon_root):
    spec = importlib.util.spec_from_file_location(
        "connectivity_api", addon_root / "freecad/forgepdm/api.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_expired_session_is_cleared_without_network(api, monkeypatch):
    client = api.ForgePDMClient("http://localhost:8000")
    client.token = "memory-only"
    client.expires_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    monkeypatch.setattr(Session, "client", client)
    monkeypatch.setattr(Session, "user", {"id": "user"})
    with pytest.raises(RuntimeError, match="expired"):
        Session.require_client()
    assert Session.client is None and Session.user is None


@pytest.mark.parametrize("failure", [TimeoutError, ConnectionRefusedError])
def test_timeout_has_structured_error_without_sensitive_response(api, monkeypatch, failure):
    client = api.ForgePDMClient("http://localhost:8000")
    client.token = "never-print-this"

    def timeout(*args, **kwargs):
        raise failure("sensitive low-level detail")

    monkeypatch.setattr(api.urllib.request, "urlopen", timeout)
    with pytest.raises(api.ForgePDMError) as error:
        client.get_item("item")
    assert error.value.code == "connection_failed"
    assert "never-print-this" not in str(error.value)
    assert "sensitive" not in str(error.value)


def test_malformed_success_is_not_returned_as_arbitrary_bytes(api):
    with pytest.raises(api.ForgePDMError) as error:
        api.ForgePDMClient._decode_response(200, b"<html>proxy login</html>")
    assert error.value.code == "invalid_response"


def test_cancelled_download_removes_partial_and_preserves_destination(api, monkeypatch, tmp_path):
    context = Context()

    class Response(io.BytesIO):
        def read(self, *args):
            context.cancelled.set()
            return super().read(*args)

    monkeypatch.setattr(api.urllib.request, "urlopen", lambda *args, **kwargs: Response(b"CAD"))
    client = api.ForgePDMClient("http://localhost:8000")
    client.token = "token"
    destination = tmp_path / "model.FCStd"
    destination.write_bytes(b"original")
    with client.operation(context), pytest.raises(OperationCancelled):
        client.download_file("file", str(destination))
    assert destination.read_bytes() == b"original"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["model.FCStd"]


def test_download_does_not_replace_existing_file(api, monkeypatch, tmp_path):
    monkeypatch.setattr(api.urllib.request, "urlopen", lambda *a, **kw: io.BytesIO(b"new"))
    client = api.ForgePDMClient("http://localhost:8000")
    client.token = "token"
    destination = tmp_path / "model.FCStd"
    destination.write_bytes(b"original")
    with pytest.raises(api.ForgePDMError, match="already exists"):
        client.download_file("file", str(destination))
    assert destination.read_bytes() == b"original"
    assert len(list(tmp_path.iterdir())) == 1


def test_catalog_paths_encode_search_and_keep_revision_id(api, monkeypatch):
    client = api.ForgePDMClient("http://localhost:8000")
    calls = []
    monkeypatch.setattr(client, "_json_request", lambda *args: calls.append(args))
    client.search_items("bolt & nut", offset=50)
    client.list_projects(editable=True)
    client.list_revisions("item")
    client.get_revision("revision-A")
    assert calls[0] == ("GET", "/api/v1/items?q=bolt+%26+nut&limit=50&offset=50")
    assert "editable=true" in calls[1][1]
    assert calls[2][1] == "/api/v1/items/item/revisions?limit=50&offset=0"
    assert calls[3] == ("GET", "/api/v1/revisions/revision-A")


def test_preferences_store_only_non_secret_fields(monkeypatch):
    from freecad.forgepdm import settings

    values = {}
    parameters = SimpleNamespace(
        GetString=lambda key, default: values.get(key, default),
        GetInt=lambda key, default: values.get(key, default),
        SetString=lambda key, value: values.update({key: value}),
        SetInt=lambda key, value: values.update({key: value}),
    )
    monkeypatch.setitem(sys.modules, "FreeCAD", SimpleNamespace(ParamGet=lambda path: parameters))
    settings.save("http://localhost:8000", "alice", 15)
    assert set(values) == {"ServerURL", "Username", "TimeoutSeconds"}
    assert settings.load() == {"url": "http://localhost:8000", "username": "alice", "timeout": 15}


@pytest.mark.parametrize(
    "url",
    [
        "https://user:secret@example.com",
        "http://example.com?token=secret",
        "http://example.com/#secret",
    ],
)
def test_url_rejects_embedded_credentials_and_query(api, url):
    with pytest.raises(ValueError):
        api.ForgePDMClient(url)


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"access_token": "token", "user": None},
        {"access_token": "token", "user": {}, "expires_at": "invalid"},
    ],
)
def test_malformed_login_does_not_set_token(api, monkeypatch, response):
    client = api.ForgePDMClient("http://localhost:8000")
    monkeypatch.setattr(client, "_json_request", lambda *args, **kwargs: response)
    with pytest.raises(api.ForgePDMError) as error:
        client.login("alice", "not-recorded")
    assert error.value.code == "invalid_response"
    assert client.token is None


def test_older_server_has_upgrade_guidance(api, monkeypatch):
    client = api.ForgePDMClient("http://localhost:8000")

    def missing(*args):
        raise api.ForgePDMError("Not Found", 404)

    monkeypatch.setattr(client, "_json_request", missing)
    with pytest.raises(api.ForgePDMError) as error:
        client.list_projects()
    assert error.value.code == "unsupported_server"
    assert "restart" in str(error.value)
