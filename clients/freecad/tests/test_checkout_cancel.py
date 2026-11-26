import json

import pytest

from freecad.forgepdm import checkout_cancel as cancel, workspace as ws
from test_workspace import Client, native


def setup(tmp_path):
    client = Client()
    revision, dataset, file_id = client.add(native())
    config = ws.retrieve(client, tmp_path, revision, dataset, file_id)
    ws.finish(client, config)
    entry = config["ledger"]["documents"][0]
    path = str(tmp_path / "configurations" / config["ledger"]["id"] / entry["path"])
    working = ws.fork_working(client.base_url, path, [])
    client.get_checkout = lambda _: dict(id="checkout", version=1, user_id="actor")
    client.datasets[revision][0]["created_at"] = "2026-11-24"
    return client, revision, working


def test_cancel_journal_survives_retry_without_replacing_lease(tmp_path):
    client, revision, path = setup(tmp_path)
    first = cancel.prepare(client, path, revision, "actor")
    client.get_checkout = lambda _: dict(id="later-checkout", version=2, user_id="actor")
    assert cancel.prepare(client, path, revision, "actor") == first
    assert first["payload"]["expected_checkout_id"] == "checkout"
    with pytest.raises(ws.WorkspaceError, match="another user"):
        cancel.prepare(client, path, revision, "other")
    client.cancellation_status = lambda *args: dict(original="result")
    client.cancel_checkout = lambda *args: pytest.fail(
        "must recover before releasing a later checkout"
    )
    assert cancel.release(client, first) == dict(original="result")


def test_pending_checkin_blocks_cancellation(tmp_path):
    client, revision, path = setup(tmp_path)
    value = ws.binding(path, client.base_url)
    (value["directory"] / "part-checkin.json").write_text(json.dumps(dict(state="prepared")))
    with pytest.raises(ws.WorkspaceError, match="pending Check In"):
        cancel.prepare(client, path, revision, "actor")
