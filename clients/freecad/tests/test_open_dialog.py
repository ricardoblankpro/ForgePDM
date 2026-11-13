"""Real offscreen Qt with fake services: keyboard flow and stale-response fencing."""

import os
import time
from threading import Event, get_ident

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from freecad.forgepdm.open_ui import OpenDialog  # noqa: E402
from freecad.forgepdm.ui import QtWidgets  # noqa: E402


class Client:
    base_url = "http://open.test"

    def __init__(self):
        self.threads = []
        self.calls = []
        self.block = Event()
        self.started = Event()

    def search_items(self, query, **options):
        self.threads.append(get_ident())
        self.calls.append((query, options))
        if query == "slow":
            self.started.set()
            self.block.wait(3)
        return {
            "items": [
                {
                    "id": query or "part",
                    "number": "P000001",
                    "name": query or "Bracket",
                    "description": "Steel",
                    "revision_label": "B",
                    "lifecycle_state": "working",
                    "current_revision_id": "B",
                }
            ],
            "offset": options["offset"],
            "has_more": False,
        }

    def list_revisions(self, item, **options):
        self.threads.append(get_ident())
        return {
            "items": [
                {"id": "B", "label": "B", "lifecycle_state": "working"},
                {"id": "A", "label": "A", "lifecycle_state": "released"},
            ],
            "offset": 0,
            "has_more": False,
        }

    def list_datasets(self, revision):
        self.threads.append(get_ident())
        return [
            {
                "id": revision + suffix,
                "dataset_type": "native_cad",
                "created_at": date,
                "files": [{"id": revision + suffix, "original_filename": "model.FCStd"}],
            }
            for suffix, date in [("old", "2026-01-01"), ("new", "2026-02-01")]
        ]


@pytest.fixture
def case(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    client = Client()
    choices = []

    def choose():
        choices.append(True)
        return str(tmp_path)

    dialog = OpenDialog(None, client, str(tmp_path), choose)
    dialog.show()

    def wait(predicate):
        deadline = time.monotonic() + 5
        while not predicate():
            app.processEvents()
            if time.monotonic() > deadline:
                raise AssertionError(dialog.status.text())
            time.sleep(0.005)
        app.processEvents()

    yield app, client, dialog, wait, choices
    client.block.set()
    if not dialog.finishing:
        dialog.reject()
    wait(lambda: not dialog.jobs)
    dialog.deleteLater()
    app.processEvents()


def test_type_enter_opens_current_revision_and_newest_snapshot_without_folder_dialog(case):
    app, client, dialog, wait, choices = case
    wait(lambda: dialog.open_button.isEnabled())
    dialog.query.setText("Bracket")
    dialog.enter_search()
    wait(lambda: dialog.selection is not None and not dialog.jobs)
    assert dialog.selection["item"]["name"] == "Bracket"
    assert dialog.selection["revision"]["id"] == "B"
    assert dialog.selection["file"]["id"] == "Bnew"
    assert choices == []
    assert get_ident() not in client.threads


def test_historical_revision_and_older_snapshot_are_selected_in_same_window(case):
    _, _, dialog, wait, _ = case
    wait(lambda: dialog.open_button.isEnabled())
    dialog.revision.setCurrentIndex(1)
    wait(lambda: dialog.open_button.isEnabled())
    assert dialog.snapshot.currentData()[1]["id"] == "Anew"
    dialog.snapshot.setCurrentIndex(1)
    dialog.request_open()
    wait(lambda: not dialog.jobs)
    assert dialog.selection["revision"]["id"] == "A"
    assert dialog.selection["file"]["id"] == "Aold"


def test_stale_search_never_replaces_latest_results_and_close_drains_requests(case):
    _, client, dialog, wait, _ = case
    wait(lambda: dialog.open_button.isEnabled())
    dialog.query.setText("slow")
    dialog.debounce.stop()
    dialog.search()
    wait(client.started.is_set)
    dialog.query.setText("latest")
    dialog.debounce.stop()
    dialog.search()
    wait(
        lambda: (
            dialog.item is not None
            and dialog.item["id"] == "latest"
            and dialog.open_button.isEnabled()
        )
    )
    client.block.set()
    wait(lambda: not dialog.jobs)
    assert dialog.item["id"] == "latest"
    dialog.reject()
    assert dialog.selection is None


def test_workspace_is_chosen_only_if_missing_and_can_be_changed_explicitly(case):
    _, _, dialog, wait, choices = case
    wait(lambda: dialog.open_button.isEnabled())
    dialog.root = ""
    dialog.request_open()
    wait(lambda: not dialog.jobs)
    assert len(choices) == 1
    assert dialog.selection["workspace"]


def test_failure_keeps_window_open_and_open_button_disabled(case):
    _, client, dialog, wait, _ = case
    wait(lambda: dialog.open_button.isEnabled())

    def fail(*args, **kwargs):
        raise RuntimeError("Session expired; log in again")

    client.list_datasets = fail
    dialog.revision.setCurrentIndex(1)
    wait(lambda: not dialog.jobs)
    assert not dialog.open_button.isEnabled()
    assert "Session expired" in dialog.status.text()
    assert dialog.selection is None
