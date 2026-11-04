"""Independent status dimensions, pin freshness and private-session boundaries."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from freecad.forgepdm import pdm_status


def remote():
    return dict(
        available=True,
        revision_id="A",
        item_number="P1",
        revision_label="A",
        lifecycle_state="working",
        checkout=None,
        newer_revision=None,
        latest_snapshot=dict(dataset_id="latest", file_id="file-new", created_at="2026-11-03"),
    )


def kinds(presentation):
    return [badge["kind"] for badge in presentation["badges"]]


def test_revision_and_snapshot_updates_and_release_coexist():
    row = remote()
    row.update(lifecycle_state="released", newer_revision=dict(label="B"))
    result = pdm_status.describe(row, dict(pin=("old", "file-old")), "checked")
    assert kinds(result) == ["released", "revision", "snapshot"]
    assert "Rev B available" in result["text"]


def test_occurrences_of_same_revision_compare_their_own_exact_pins():
    row = remote()
    current = pdm_status.describe(row, dict(pin=("latest", "file-new")), "checked")
    older = pdm_status.describe(row, dict(pin=("old", "file-old")), "checked")
    assert "snapshot" not in kinds(current) and "snapshot" in kinds(older)


def test_checkout_colors_distinguish_self_and_others_and_expiry():
    row = remote()
    now = datetime.now(timezone.utc)
    row["checkout"] = dict(
        display_name="Alice <script>",
        username="alice",
        is_mine=False,
        expires_at=(now + timedelta(minutes=1)).isoformat(),
    )
    other = pdm_status.describe(row, {}, "checked", now=now)
    assert "other" in kinds(other) and "<script>" not in other["tooltip"]
    row["checkout"]["is_mine"] = True
    assert "mine" in kinds(pdm_status.describe(row, {}, "checked", now=now))
    assert "mine" not in kinds(
        pdm_status.describe(row, {}, "checked", now=now + timedelta(minutes=2))
    )


def test_unknown_pins_never_claim_current_and_local_edits_are_explicit():
    result = pdm_status.describe(remote(), dict(pin=None, dirty=True), "checked")
    assert "current" not in result["text"] and "local" in kinds(result)


def test_offline_is_stale_even_with_cached_released_and_update_status():
    row = remote()
    row["lifecycle_state"] = "released"
    result = pdm_status.describe(row, dict(pin=("old", "old")), "checked", stale="Offline")
    assert kinds(result) == ["unknown"] and result["text"] == "Stale status"
    assert "last known" in result["tooltip"] and "Offline" in result["tooltip"]


def test_removed_permission_does_not_retain_owner_or_revision_details():
    result = pdm_status.describe(dict(available=False), {}, "checked")
    assert result["text"] == "Status unavailable"
    assert "Alice" not in result["tooltip"]


def test_worker_batches_revisions_and_preserves_missing_local_pins(monkeypatch):
    from freecad.forgepdm.workspace import WorkspaceError

    def unbound(*args, **kwargs):
        raise WorkspaceError("Unmanaged snapshot")

    monkeypatch.setattr(pdm_status.workspace, "binding", unbound)
    calls = []
    client = SimpleNamespace(base_url="http://server", _checkpoint=lambda: None)

    def query(ids):
        calls.append(ids)
        return dict(checked_at="now", items=[dict(revision_id=i, available=False) for i in ids])

    client.revision_status = query
    targets = [
        dict(key=i, revision_id=str(i), item_id="item", path="unbound", dirty=False)
        for i in range(205)
    ]
    result = pdm_status.fetch(client, targets, {})
    assert [len(page) for page in calls] == [200, 5]
    assert len(result["remote"]) == len(result["local"]) == 205
    assert all(value["pin"] is None for value in result["local"].values())


def test_hash_cache_is_invalidated_when_saved_bytes_change(monkeypatch, tmp_path):
    from freecad.forgepdm import workspace

    path = tmp_path / "model.FCStd"
    path.write_bytes(b"initial")
    original = workspace.digest(path)[0]
    entry = dict(
        path=path.name,
        item_id="item",
        revision_id="rev",
        dataset_id="latest",
        file_id="file-new",
        working_hash=original,
    )
    monkeypatch.setattr(
        workspace, "binding", lambda *a, **kw: dict(directory=tmp_path, entry=entry)
    )
    target = dict(key="doc", item_id="item", revision_id="rev", path=str(path), dirty=False)
    client = SimpleNamespace(
        base_url="http://server",
        _checkpoint=lambda: None,
        revision_status=lambda ids: dict(checked_at="now", items=[]),
    )
    cache = {}
    assert not pdm_status.fetch(client, [target], cache)["local"]["doc"]["dirty"]
    path.write_bytes(b"saved but unuploaded edit")
    assert pdm_status.fetch(client, [target], cache)["local"]["doc"]["dirty"]


def test_session_switch_notifies_status_without_importing_gui(monkeypatch):
    import sys
    from freecad.forgepdm.session import Session

    notifications = []
    monkeypatch.setitem(
        sys.modules,
        "freecad.forgepdm.tree_status",
        SimpleNamespace(session_changed=lambda: notifications.append(True)),
    )
    previous = Session.client, Session.user
    try:
        Session.set_client(SimpleNamespace(token="memory-only"), dict(id="other"))
        Session.clear()
        assert len(notifications) == 2
    finally:
        Session.client, Session.user = previous
