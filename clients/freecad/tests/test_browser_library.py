"""Shortcut privacy, exact snapshot history, bounded growth and corrupt-state safety."""

import json
from uuid import uuid4

import pytest

from freecad.forgepdm import settings
from freecad.forgepdm.browser_library import BrowserLibrary


class Parameters:
    def __init__(self):
        self.values, self.children = {}, {}

    def GetGroup(self, key):
        return self.children.setdefault(key, Parameters())

    def SetString(self, key, value):
        self.values[key] = value

    def GetString(self, key, default):
        return self.values.get(key, default)


@pytest.fixture
def libraries(monkeypatch):
    parameters = Parameters()
    monkeypatch.setattr(settings, "_parameters", lambda: parameters)
    return (
        BrowserLibrary("http://one", "alice"),
        BrowserLibrary("http://one", "bob"),
        BrowserLibrary("http://two", "alice"),
    )


def selection(item=None, revision=None):
    return {
        "item": {"id": item or str(uuid4())},
        "revision": {"id": revision or str(uuid4())},
        "dataset": {"id": str(uuid4())},
        "file": {"id": str(uuid4())},
    }


def test_favorites_are_private_to_server_account_and_toggle_without_server_writes(libraries):
    alice, bob, other = libraries
    item = str(uuid4())
    alice.toggle_favorite(item)
    assert alice.load()["favorites"] == [item]
    assert bob.load() == other.load() == {"favorites": [], "recent": []}
    alice.toggle_favorite(item)
    assert alice.load()["favorites"] == []


def test_recent_retains_exact_pins_deduplicates_and_is_bounded(libraries):
    alice, *_ = libraries
    first = selection()
    second = selection(first["item"]["id"], first["revision"]["id"])
    alice.add_recent(first)
    alice.add_recent(second)
    alice.add_recent(first)
    recent = alice.load()["recent"]
    assert len(recent) == 2
    assert recent[0]["file_id"] == first["file"]["id"]
    assert recent[1]["file_id"] == second["file"]["id"]
    for _ in range(35):
        alice.add_recent(selection())
    assert len(alice.load()["recent"]) == 30
    alice.clear_recent()
    assert alice.load()["recent"] == []


def test_corrupt_shortcuts_are_preserved_and_credentials_are_not_serialized(libraries):
    alice, *_ = libraries
    group = settings._workspace_parameters(alice.server, alice.actor)
    group.SetString("BrowserLibrary", '{"favorites":["../private"],"recent":[]}')
    before = group.GetString("BrowserLibrary", "")
    with pytest.raises(ValueError, match="preserved"):
        alice.toggle_favorite(str(uuid4()))
    assert group.GetString("BrowserLibrary", "") == before
    group.SetString("BrowserLibrary", "")
    request = selection()
    request.update(access_token="secret", workspace="/private/path")
    alice.add_recent(request)
    text = group.GetString("BrowserLibrary", "")
    assert "secret" not in text and "workspace" not in text and "path" not in text
    assert set(json.loads(text)["recent"][0]) == {"item_id", "revision_id", "dataset_id", "file_id"}
