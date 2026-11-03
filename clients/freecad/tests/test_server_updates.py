"""Server refresh compares exact snapshots and preserves local documents."""

import json
from types import SimpleNamespace

import pytest

from test_document_save import commands as commands_fixture

commands = commands_fixture


@pytest.fixture
def context(commands, monkeypatch, tmp_path):
    from freecad.forgepdm import server_updates as updates

    path = tmp_path / "model.FCStd"
    path.write_bytes(b"local")
    client = SimpleNamespace(base_url="http://server", _checkpoint=lambda: None)
    entry = dict(
        item_id="item",
        revision_id="rev",
        dataset_id="old",
        file_id="oldfile",
        working_hash=updates.workspace.digest(path)[0],
    )
    value = dict(root=tmp_path, directory=tmp_path, entry=entry)
    monkeypatch.setattr(updates.workspace, "binding", lambda *a: value)
    client.get_revision = lambda _: dict(item_id="item")
    client.newer_revisions = lambda *a: [dict(label="B")]
    old = dict(
        id="old",
        dataset_type="native_cad",
        created_at="2026-11-01",
        files=[dict(id="oldfile", content_hash="aaa")],
    )
    new = dict(
        id="new",
        dataset_type="native_cad",
        created_at="2026-11-03",
        files=[dict(id="newfile", content_hash="bbb")],
    )
    client.list_datasets = lambda _: [new, old]
    client.inspect_server_update = lambda *a: updates.inspect(client, *a)
    client.update_baseline = lambda *a: updates.baseline(client, *a)
    return updates, client, path, entry, new


def test_latest_snapshot_is_selected_by_date_not_response_order(context):
    updates, client, path, entry, new = context
    result = updates.inspect(client, path, "item", "rev")
    assert result["changed"] and result["dataset"] == new
    assert result["newer"] == [dict(label="B")]
    entry.update(dataset_id="new", file_id="newfile")
    assert not updates.inspect(client, path, "item", "rev")["changed"]


def test_component_preparation_skips_current_occurrences_and_keeps_exact_revision(
    context, monkeypatch
):
    updates, client, path, _, _ = context
    client.get_revision = lambda _: dict(item_id="item", id="rev", lifecycle_state="working")
    refs = [
        dict(object_name=n, target_item_id="item", target_revision_id="rev")
        for n in ("First", "Second")
    ]
    pins = [
        dict(object_name="First", target_dataset_id="old", target_file_id="oldfile"),
        dict(object_name="Second", target_dataset_id="new", target_file_id="newfile"),
    ]
    monkeypatch.setattr(updates.workspace, "bind_references", lambda *a: pins)
    result = updates.prepare_components(client, path, "item", "rev", refs)
    assert result["names"] == ["First"] and result["pins"] == pins
    assert result["revision"]["id"] == "rev"


def test_component_preparation_rejects_mixed_revision_selection(context):
    updates, client, path, _, _ = context
    refs = [dict(target_item_id="item", target_revision_id=rev) for rev in ("A", "B")]
    with pytest.raises(updates.workspace.WorkspaceError, match="one component"):
        updates.prepare_components(client, path, "item", "rev", refs)


def component_command(commands, context, monkeypatch):
    from freecad.forgepdm import replacement

    client, document, messages = setup_command(commands, context, monkeypatch)
    updates, _, path, _, new = context
    metadata = document.getObject("ForgePDM_Metadata")
    links = {
        name: SimpleNamespace(Name=name, Label=name, Document=document)
        for name in ("First", "Second")
    }
    document.getObject = lambda name: metadata if name == "ForgePDM_Metadata" else links[name]
    refs = [
        dict(
            object_name=name,
            target_item_id="item",
            target_revision_id="rev",
            target_object_name="Box",
            target_path="child.FCStd",
            component_label="P1 / A",
        )
        for name in links
    ]
    pins = [
        dict(
            object_name="First",
            target_revision_id="rev",
            target_object_name="Box",
            property_name="LinkedObject",
            target_path="child.FCStd",
            target_dataset_id="old",
            target_file_id="oldfile",
        )
    ]
    parent = updates.baseline(client, path, "item", "rev")
    update = dict(
        baseline=parent,
        names=["First"],
        pins=pins,
        dataset=new,
        file=new["files"][0],
        revision=dict(id="rev", item_id="item", label="A", lifecycle_state="working"),
    )
    client.prepare_component_update = lambda *a: update
    client.component_update_baseline = lambda *a: dict(baseline=parent, pins=pins)
    client.validate_references = lambda *a: pins
    client.retrieve_configuration = lambda *a: {}
    client.finish_configuration = lambda *a: None

    def authorize(*a):
        yield from ()
        return {}

    monkeypatch.setattr(commands, "_editable", authorize)
    monkeypatch.setattr(commands, "_authorize_tree_labels", authorize)
    monkeypatch.setattr(commands.tree_observer, "allow_edit", lambda *a: None)
    monkeypatch.setattr(commands.cad, "capture_bom", lambda *a: refs)
    monkeypatch.setattr(
        commands.FreeCADGui,
        "Selection",
        SimpleNamespace(getSelection=lambda: [links["First"]]),
        raising=False,
    )
    monkeypatch.setattr(commands, "select_replacement_occurrences", lambda *a: ["First"])
    monkeypatch.setattr(commands, "review_component_replacement", lambda *a: True)
    monkeypatch.setattr(commands, "_choose_workspace", lambda *a: str(path.parent))
    monkeypatch.setattr(
        commands.cad, "open_configuration", lambda *a: dict(root=SimpleNamespace(), owned=[])
    )
    monkeypatch.setattr(commands.cad, "close_owned", lambda *a: [])
    monkeypatch.setattr(commands.FreeCAD, "setActiveDocument", lambda *a: None, raising=False)
    calls = []
    monkeypatch.setattr(replacement, "apply", lambda *a, **kw: calls.append((a, kw)) or 1)
    return client, update, calls, messages


def test_selected_component_command_applies_explicit_snapshot_mode(commands, context, monkeypatch):
    client, update, calls, _ = component_command(commands, context, monkeypatch)
    commands.UpdateSelectedComponentsCommand().Activated()
    assert not commands._test_errors and len(calls) == 1
    args, kwargs = calls[0]
    assert args[2] == ["First"]
    assert args[1][0]["target_file_id"] == "oldfile"
    assert kwargs == dict(target_snapshot=dict(dataset_id="new", file_id="newfile"))


def test_selected_component_cancel_does_not_apply(commands, context, monkeypatch):
    client, update, calls, _ = component_command(commands, context, monkeypatch)
    monkeypatch.setattr(commands, "review_component_replacement", lambda *a: False)
    commands.UpdateSelectedComponentsCommand().Activated()
    assert not calls and not commands._test_errors


def test_selected_component_pin_change_during_review_blocks_apply(commands, context, monkeypatch):
    client, update, calls, _ = component_command(commands, context, monkeypatch)
    client.component_update_baseline = lambda *a: dict(baseline=update["baseline"], pins=[])
    commands.UpdateSelectedComponentsCommand().Activated()
    assert not calls and "snapshots changed" in commands._test_errors[0]


def test_current_selected_components_do_not_retrieve(commands, context, monkeypatch):
    client, update, calls, messages = component_command(commands, context, monkeypatch)
    update["names"] = []
    client.retrieve_configuration = lambda *a: pytest.fail("Already current component downloaded")
    commands.UpdateSelectedComponentsCommand().Activated()
    assert not calls and not commands._test_errors
    assert "already use the latest" in messages[-1]


def test_saved_unuploaded_changes_block_refresh(context):
    updates, client, path, _, _ = context
    path.write_bytes(b"unuploaded edits")
    with pytest.raises(updates.workspace.WorkspaceError, match="local changes"):
        updates.inspect(client, path, "item", "rev")


@pytest.mark.parametrize("state", ["prepared", "committed", "unknown"])
def test_pending_recovery_blocks_refresh(context, state):
    updates, client, path, _, _ = context
    (path.parent / updates.part_checkin.JOURNAL).write_text(json.dumps(dict(state=state)))
    with pytest.raises(updates.workspace.WorkspaceError, match="pending Check In"):
        updates.inspect(client, path, "item", "rev")


def test_acknowledged_recovery_allows_refresh(context):
    updates, client, path, _, _ = context
    (path.parent / updates.part_checkin.JOURNAL).write_text('{"state":"acknowledged"}')
    assert updates.inspect(client, path, "item", "rev")["changed"]


def setup_command(commands, context, monkeypatch):
    updates, client, path, _, _ = context
    metadata = SimpleNamespace(ItemId="item", RevisionId="rev", ItemNumber="P1", RevisionLabel="A")
    document = SimpleNamespace(Name="original", FileName=str(path), getObject=lambda _: metadata)
    commands.FreeCAD.ActiveDocument = document
    monkeypatch.setattr(commands.FreeCAD, "getDocument", lambda _: document, raising=False)
    monkeypatch.setattr(commands.cad, "document_modified", lambda _: False)
    monkeypatch.setattr(commands.Session, "require_client", lambda: client)
    messages = []
    monkeypatch.setattr(commands, "information", lambda *a: messages.append(a[-1]))
    return client, document, messages


def test_cancel_does_not_retrieve_or_modify(commands, context, monkeypatch):
    client, document, _ = setup_command(commands, context, monkeypatch)
    monkeypatch.setattr(commands, "ask_choice", lambda *a: "Cancel")
    commands.UpdateFromServerCommand().Activated()
    assert not commands._test_errors
    assert commands.FreeCAD.ActiveDocument is document


def test_dirty_document_blocks_before_network(commands, context, monkeypatch):
    setup_command(commands, context, monkeypatch)
    monkeypatch.setattr(commands.cad, "document_modified", lambda _: True)
    commands.UpdateFromServerCommand().Activated()
    assert "Local document changed" in commands._test_errors[0]


def test_update_opens_exact_reviewed_copy_and_keeps_original(commands, context, monkeypatch):
    client, document, messages = setup_command(commands, context, monkeypatch)
    calls = []
    monkeypatch.setattr(commands, "ask_choice", lambda *a: "Open updated copy")
    client.retrieve_configuration = lambda *a: calls.append(a) or {"new": True}
    client.finish_configuration = lambda configuration: calls.append("finished")
    new_document = SimpleNamespace(Name="updated")
    monkeypatch.setattr(
        commands.cad, "open_configuration", lambda *a: dict(root=new_document, owned=[new_document])
    )
    monkeypatch.setattr(
        commands.FreeCAD, "setActiveDocument", lambda name: calls.append(name), raising=False
    )
    commands.UpdateFromServerCommand().Activated()
    assert not commands._test_errors
    assert calls[0][1:] == ("rev", "new", "newfile")
    assert calls[-2:] == ["finished", "updated"]
    assert commands.FreeCAD.getDocument("original") is document
    assert "original remains open" in messages[-1]


def test_edit_during_transfer_aborts_before_open(commands, context, monkeypatch):
    client, document, _ = setup_command(commands, context, monkeypatch)
    monkeypatch.setattr(commands, "ask_choice", lambda *a: "Open updated copy")
    dirty = []
    client.retrieve_configuration = lambda *a: dirty.append(True) or {"new": True}
    monkeypatch.setattr(commands.cad, "document_modified", lambda _: bool(dirty))
    incomplete = []
    monkeypatch.setattr(commands.workspace, "incomplete", incomplete.append)
    monkeypatch.setattr(commands.FreeCAD, "setActiveDocument", lambda _: None, raising=False)
    commands.UpdateFromServerCommand().Activated()
    assert "Local document changed" in commands._test_errors[0]
    assert incomplete == [{"new": True}]
