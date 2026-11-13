"""Authorized shortcut resolution, historical pins and checkout pagination."""

from types import SimpleNamespace

import pytest

from freecad.forgepdm.api import ForgePDMError
from freecad.forgepdm.open_model import shortcut_items


def client():
    def get_item(item):
        if item == "hidden":
            raise ForgePDMError("item not found", 404)
        return {
            "id": item,
            "number": "P000001",
            "name": "model",
            "description": "",
            "current_revision_id": "B",
        }

    def get_revision(revision):
        return {
            "id": revision,
            "item_id": "part",
            "label": revision,
            "lifecycle_state": "released" if revision == "A" else "working",
            "description_record": {"description": "STEEL PLATE"},
        }

    return SimpleNamespace(get_item=get_item, get_revision=get_revision)


def test_recent_resolves_recorded_revision_and_snapshot_not_current():
    result = shortcut_items(
        client(),
        "recent",
        [{"item_id": "part", "revision_id": "A", "dataset_id": "dataset-A", "file_id": "file-A"}],
    )
    row = result["items"][0]
    assert row["current_revision_id"] == "B"
    assert row["preferred_revision"]["id"] == "A"
    assert row["preferred_file_id"] == "file-A"
    assert row["revision_label"] == "A" and row["revision_description"] == "STEEL PLATE"


def test_favorite_refreshes_current_metadata_and_omits_inaccessible_ids():
    result = shortcut_items(
        client(), "favorites", ["hidden", "part"], query="steel", number_series="P"
    )
    assert [row["id"] for row in result["items"]] == ["part"]
    assert "preferred_revision" not in result["items"][0]
    assert result["unavailable"] == 1
    assert shortcut_items(client(), "favorites", ["part"], query="aluminum")["items"] == []


def test_checkout_resolution_filters_after_scanning_pages_and_preserves_expiry():
    api = client()
    calls = []

    def checkouts(limit, offset):
        calls.append(offset)
        return {
            "items": [
                {
                    "item_id": "part",
                    "revision_id": "A" if offset == 0 else "B",
                    "status": "expired" if offset == 0 else "active",
                }
            ],
            "has_more": offset == 0,
            "limit": 1,
        }

    api.my_checkouts = checkouts
    result = shortcut_items(api, "checkouts", [], query="steel", limit=1, offset=1)
    assert calls == [0, 1]
    assert result["items"][0]["preferred_revision"]["id"] == "B"
    assert result["items"][0]["checkout_status"] == "active"
    assert not result["has_more"]
    assert shortcut_items(api, "checkouts", [], limit=1)["items"][0]["checkout_status"] == "expired"


def test_expired_session_is_not_silently_treated_as_empty_and_mismatched_pins_fail():
    api = client()
    api.get_item = lambda _: (_ for _ in ()).throw(ForgePDMError("expired", 401))
    with pytest.raises(ForgePDMError):
        shortcut_items(api, "favorites", ["part"])
    api = client()
    api.get_item = lambda _: {
        "id": "other",
        "number": "P000002",
        "name": "model",
        "current_revision_id": "B",
    }
    with pytest.raises(ValueError, match="different item"):
        shortcut_items(api, "favorites", ["other"])
