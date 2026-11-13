"""Local ID-only shortcuts, separated by authenticated server and account."""

import json
from uuid import UUID

from . import settings

MAX_FAVORITES = 100
MAX_RECENT = 30
PIN_FIELDS = ("item_id", "revision_id", "dataset_id", "file_id")


def normalize(value):
    if not isinstance(value, dict) or set(value) != {"favorites", "recent"}:
        raise ValueError("Saved browser shortcuts need inspection; they were preserved.")
    favorites, recent = value["favorites"], value["recent"]
    if not isinstance(favorites, list) or not isinstance(recent, list):
        raise ValueError("Invalid browser shortcuts; they were preserved.")
    if len(favorites) > MAX_FAVORITES or len(recent) > MAX_RECENT:
        raise ValueError("Too many saved browser shortcuts; they were preserved.")
    try:
        favorites = list(dict.fromkeys(str(UUID(item)) for item in favorites))
        pins = []
        for entry in recent:
            if not isinstance(entry, dict) or set(entry) != set(PIN_FIELDS):
                raise ValueError("invalid recent snapshot")
            pin = {field: str(UUID(entry[field])) for field in PIN_FIELDS}
            if pin not in pins:
                pins.append(pin)
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError("Invalid browser shortcut identities; they were preserved.") from error
    return {"favorites": favorites, "recent": pins}


class BrowserLibrary:
    def __init__(self, server, actor):
        if not server or not actor:
            raise ValueError("A signed-in account is required for browser shortcuts")
        self.server, self.actor = server, actor

    def load(self):
        text = settings._workspace_parameters(self.server, self.actor).GetString(
            "BrowserLibrary", ""
        )
        return normalize(json.loads(text)) if text else {"favorites": [], "recent": []}

    def save(self, value):
        value = normalize(value)
        settings._workspace_parameters(self.server, self.actor).SetString(
            "BrowserLibrary", json.dumps(value)
        )

    def toggle_favorite(self, item):
        item = str(UUID(item))
        value = self.load()
        if item in value["favorites"]:
            value["favorites"].remove(item)
        else:
            if len(value["favorites"]) >= MAX_FAVORITES:
                raise ValueError(
                    "You can save up to 100 favorites. Remove one before adding another."
                )
            value["favorites"].append(item)
        self.save(value)

    def add_recent(self, selection):
        pin = {
            "item_id": selection["item"]["id"],
            "revision_id": selection["revision"]["id"],
            "dataset_id": selection["dataset"]["id"],
            "file_id": selection["file"]["id"],
        }
        pin = normalize({"favorites": [], "recent": [pin]})["recent"][0]
        value = self.load()
        value["recent"] = [pin] + [entry for entry in value["recent"] if entry != pin]
        value["recent"] = value["recent"][:MAX_RECENT]
        self.save(value)

    def clear_recent(self):
        value = self.load()
        value["recent"] = []
        self.save(value)
