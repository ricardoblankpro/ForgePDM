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


def test_fastener_reads_are_deduplicated_exact_and_language_is_frozen(monkeypatch):
    monkeypatch.setattr(
        pdm_status.workspace, "binding", lambda *a, **k: (_ for _ in ()).throw(ValueError())
    )
    client = SimpleNamespace(
        base_url="http://server", description_language="pt-BR", _checkpoint=lambda: None
    )
    calls = []

    def query(ids, language=None):
        calls.append((ids, language))
        client.description_language = "en"
        return dict(checked_at="now", items=[])

    client.revision_status = query
    targets = [
        dict(
            key="assembly",
            revision_id="assembly-A",
            item_id="assembly",
            path="",
            dirty=True,
            fasteners={str(i): dict(revision_id="standard-A" + str(i // 2)) for i in range(402)},
        )
    ]
    result = pdm_status.fetch(client, targets, {})
    assert [len(ids) for ids, _ in calls] == [200, 2]
    assert all(language == "pt-BR" for _, language in calls)
    assert calls[0][0][0] == "assembly-A" and calls[0][0][1] == "standard-A0"
    assert result["language"] == "pt-BR" and list(result["local"]) == ["assembly"]


def description_fixture():
    target = dict(
        revision_id="assembly-A", description="Assembly", description_token="original", dirty=True
    )
    occurrence = dict(
        revision_id="standard-A", description="Type: ISO4017; Diameter: M8; Length: 20"
    )
    snapshot = dict(
        language="pt-BR",
        remote={
            "assembly-A": dict(
                available=True,
                description="Assembly",
                description_token="original",
                localized_description=dict(original_text="Assembly", text="Conjunto"),
            ),
            "standard-A": dict(
                available=True,
                description="SCREW ISO4017 M8X20",
                localized_description=dict(
                    original_text="SCREW ISO4017 M8X20", text="PARAFUSO ISO4017 M8X20"
                ),
            ),
            "standard-B": dict(available=True, description="WRONG NEW REVISION"),
        },
    )
    return target, occurrence, snapshot


def test_fastener_uses_its_own_revision_and_never_the_assembly_description():
    target, occurrence, snapshot = description_fixture()
    assert (
        pdm_status.description_text(target, snapshot, "pt-BR", occurrence)
        == "PARAFUSO ISO4017 M8X20"
    )
    assert pdm_status.description_text(target, snapshot, None, occurrence) == "SCREW ISO4017 M8X20"
    assert pdm_status.description_text(target, snapshot, "en", occurrence) == "SCREW ISO4017 M8X20"


def test_unassociated_or_inaccessible_fastener_uses_only_local_geometry():
    target, occurrence, snapshot = description_fixture()
    snapshot["remote"]["standard-A"] = dict(available=False)
    assert (
        pdm_status.description_text(target, snapshot, "pt-BR", occurrence)
        == occurrence["description"]
    )
    occurrence["revision_id"] = None
    assert (
        pdm_status.description_text(target, snapshot, "pt-BR", occurrence)
        == occurrence["description"]
    )


def test_local_description_edits_are_preserved_but_geometry_edits_allow_translation():
    target, _, snapshot = description_fixture()
    assert pdm_status.description_text(target, snapshot, "pt-BR") == "Conjunto"
    target["description"] = "Unsaved new assembly description"
    assert pdm_status.description_text(target, snapshot, "pt-BR") == target["description"]
    target["dirty"] = False
    snapshot["remote"]["assembly-A"]["description_token"] = "new-source"
    assert pdm_status.description_text(target, snapshot, "pt-BR") == "Conjunto"
