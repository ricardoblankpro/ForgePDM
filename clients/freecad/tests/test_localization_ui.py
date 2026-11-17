"""Real Qt translation actions remain server writes, including for released sources."""

import copy
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from freecad.forgepdm.localization_ui import edit  # noqa: E402
from freecad.forgepdm.ui import QtWidgets  # noqa: E402


@pytest.mark.parametrize("can_edit", [True, False])
def test_translation_editor_respects_server_permissions_and_current_draft(can_edit):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    record = {
        "id": "source",
        "field": "designation",
        "source": {"language": "pt-BR", "text": "Conjunto"},
        "translations": [],
        "token": "old",
        "can_edit": can_edit,
    }
    calls = []

    def request(method, path, payload=None):
        calls.append((method, path, payload))
        if method == "GET":
            return [copy.deepcopy(record)]
        assert payload["expected_token"] == record["token"]
        record["token"] = "new"
        record["translations"] = [
            {
                "id": "draft",
                "language": "en",
                "text": payload["text"],
                "state": "approved" if payload["operation"] == "approve" else "draft",
                "superseded_at": None,
                "provenance_json": "{}",
            }
        ]
        return copy.deepcopy(record)

    def start(label, fn, args, kwargs, valid, done):
        result = fn(*args, **kwargs)
        if valid():
            done(result)

    host = QtWidgets.QWidget()
    view = SimpleNamespace(
        item={"id": "item"},
        revision=SimpleNamespace(currentData=lambda: {"id": "revision"}),
        client=SimpleNamespace(_json_request=request),
        start=start,
    )
    edit(host, view)
    dialog = view._localization_dialog
    try:
        app.processEvents()
        buttons = {b.text(): b for b in dialog.findChildren(QtWidgets.QPushButton)}
        text = dialog.findChild(QtWidgets.QPlainTextEdit)
        assert buttons["Save draft"].isEnabled() == can_edit
        assert text.isReadOnly() != can_edit
        if can_edit:
            text.setPlainText("Assembly")
            buttons["Save draft"].click()
            assert calls[-1][2]["operation"] == "draft"
            count = len(calls)
            text.setPlainText("Unsaved change")
            buttons["Approve draft"].click()
            assert len(calls) == count
            text.setPlainText("Assembly")
            buttons["Approve draft"].click()
            assert calls[-1][2]["translation_id"] == "draft"
            assert record["translations"][0]["state"] == "approved"
        else:
            buttons["Save draft"].click()
            assert len(calls) == 1
    finally:
        dialog.close()
        host.close()
        app.processEvents()
