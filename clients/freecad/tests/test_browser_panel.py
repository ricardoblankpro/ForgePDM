"""Real Qt modeless browser: shortcuts, pin selection, hide/reuse and account isolation."""

import os
import time
from copy import deepcopy
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from test_open_dialog import Client  # noqa: E402

from freecad.forgepdm import browser_library, browser_panel  # noqa: E402
from freecad.forgepdm.open_model import shortcut_items  # noqa: E402
from freecad.forgepdm.session import Session  # noqa: E402
from freecad.forgepdm.ui import QtWidgets  # noqa: E402


class API(Client):
    token = "memory-only"

    def get_item(self, item):
        return {
            "id": item,
            "number": "P000001",
            "name": "Hidden generic name",
            "description": "Steel",
            "current_revision_id": "B",
        }

    def get_revision(self, revision):
        return {
            "id": revision,
            "item_id": "part",
            "label": revision,
            "lifecycle_state": "working" if revision == "B" else "released",
            "description_record": {"description": "Steel"},
        }

    def my_checkouts(self, limit=50, offset=0):
        return {
            "items": [
                {"item_id": "part", "revision_id": "B", "status": "active"},
                {"item_id": "part", "revision_id": "A", "status": "expired"},
            ],
            "limit": limit,
            "offset": offset,
            "has_more": False,
        }

    def browser_items(self, *args, **kwargs):
        return shortcut_items(self, *args, **kwargs)


class Library:
    states = {}

    def __init__(self, server, actor):
        self.key = server, actor
        self.states.setdefault(self.key, {"favorites": [], "recent": []})

    def load(self):
        return deepcopy(self.states[self.key])

    def toggle_favorite(self, item):
        values = self.states[self.key]["favorites"]
        values.remove(item) if item in values else values.append(item)

    def clear_recent(self):
        self.states[self.key]["recent"] = []


@pytest.fixture
def case(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = QtWidgets.QMainWindow()
    host.resize(1100, 800)
    Library.states = {}
    monkeypatch.setattr(browser_library, "BrowserLibrary", Library)
    client = API()
    previous = Session.client, Session.user
    Session.set_client(client, {"id": "alice"})
    requests = []
    job = SimpleNamespace(done=False, error=None)

    def opening(selection):
        requests.append(selection)
        return job

    dock = browser_panel.show_browser(
        host, client, "alice", str(tmp_path), lambda: str(tmp_path), opening
    )
    host.show()

    def wait(predicate):
        deadline = time.monotonic() + 5
        while not predicate():
            app.processEvents()
            if time.monotonic() > deadline:
                raise AssertionError("browser event loop timed out")
            time.sleep(0.005)
        app.processEvents()

    wait(lambda: dock.view.open_button.isEnabled())
    yield app, host, client, dock, wait, requests, job
    client.block.set()
    job.done = True
    Session.clear()
    wait(lambda: not dock.view.jobs and dock.view.open_job is None)
    browser_panel._dock = None
    Session.set_client(*previous)
    host.deleteLater()
    app.processEvents()


def test_name_column_removed_and_favorites_are_one_click_tabs(case):
    _, _, _, dock, wait, _, _ = case
    view = dock.view
    assert [view.results.headerItem().text(i) for i in range(view.results.columnCount())] == [
        "Item",
        "Description",
        "Revision",
        "Lifecycle",
    ]
    assert view.results.topLevelItem(0).text(1) == "Steel"
    view.favorite.click()
    assert "★" in view.favorite.text()
    view.source.setCurrentIndex(2)
    wait(lambda: view.item is not None and view.open_button.isEnabled())
    assert view.item["id"] == "part"
    view.favorite.click()
    wait(lambda: not view.jobs)
    assert view.results.topLevelItemCount() == 0


def test_recent_keeps_old_snapshot_and_missing_pin_does_not_fall_back(case):
    _, _, _, dock, wait, _, _ = case
    view = dock.view
    view.library.states[view.library.key]["recent"] = [
        {"item_id": "part", "revision_id": "A", "dataset_id": "Aold", "file_id": "Aold"}
    ]
    view.source.setCurrentIndex(1)
    wait(lambda: view.open_button.isEnabled() and view.revision.currentData()["id"] == "A")
    assert view.snapshot.currentData()[1]["id"] == "Aold"
    view.library.states[view.library.key]["recent"][0]["file_id"] = "missing"
    view.search()
    wait(lambda: not view.jobs)
    assert not view.open_button.isEnabled()
    assert "recorded upload is unavailable" in view.status.text()
    view.snapshot.setCurrentIndex(0)
    assert view.open_button.isEnabled()


def test_my_checkouts_shows_expired_status_and_opens_without_closing_panel(case):
    _, _, _, dock, wait, requests, job = case
    view = dock.view
    view.source.setCurrentIndex(3)
    wait(lambda: not view.jobs and view.results.topLevelItemCount() == 2)
    assert "expired checkout" in view.results.topLevelItem(1).text(3)
    view.results.setCurrentItem(view.results.topLevelItem(1))
    wait(lambda: view.open_button.isEnabled())
    view.request_open()
    assert requests[0]["revision"]["id"] == "A"
    assert requests[0]["actor_id"] == "alice"
    assert dock.isVisible() and not view.finishing and not view.isEnabled()
    job.done = True
    wait(lambda: view.open_job is None)
    assert view.isEnabled() and dock.isVisible()


def test_hiding_and_toolbar_reuse_keep_one_panel_and_logout_clears_it(case):
    _, host, client, dock, wait, _, _ = case
    view = dock.view
    view.favorite.click()
    dock.hide()
    assert not dock.isVisible()
    again = browser_panel.show_browser(
        host, client, "alice", view.root, lambda: view.root, lambda _: None
    )
    assert again is dock
    wait(lambda: view.open_button.isEnabled())
    assert "★" in view.favorite.text()
    Session.clear()
    assert not dock.isVisible()
    assert view.results.topLevelItemCount() == 0
    assert not view.workspace.text()
    assert browser_panel._dock is None
    Session.set_client(client, {"id": "bob"})
    other = browser_panel.show_browser(
        host, client, "bob", view.root, lambda: view.root, lambda _: None
    )
    other.view.source.setCurrentIndex(2)
    wait(lambda: not other.view.jobs)
    assert other.view.results.topLevelItemCount() == 0
    assert other.view.library.load()["favorites"] == []


def test_account_switch_while_search_is_in_flight_cannot_deliver_old_rows(case):
    _, host, client, dock, wait, _, _ = case
    view = dock.view
    view.query.setText("slow")
    view.debounce.stop()
    view.search()
    wait(client.started.is_set)
    other_client = API()
    Session.set_client(other_client, {"id": "bob"})
    assert view.results.topLevelItemCount() == 0
    other = browser_panel.show_browser(
        host, other_client, "bob", view.root, lambda: view.root, lambda _: None
    )
    other.view.source.setCurrentIndex(2)
    client.block.set()
    wait(lambda: not view.jobs and not other.view.jobs)
    assert other.view.results.topLevelItemCount() == 0
    assert other.view.library.load()["recent"] == []


def test_server_checkouts_remain_available_when_local_shortcuts_are_corrupt(case):
    _, _, _, dock, wait, _, _ = case
    view = dock.view

    def corrupt():
        raise ValueError("Saved shortcuts need inspection")

    view.library.load = corrupt
    view.source.setCurrentIndex(3)
    wait(lambda: not view.jobs and view.results.topLevelItemCount() == 2)
    assert view.open_button.isEnabled()
    assert not view.favorite.isEnabled()
