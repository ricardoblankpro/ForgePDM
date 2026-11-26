"""Local generation integrity and child-first publication policy."""

import pytest

from freecad.forgepdm import managed_session as session, workspace as ws
from test_workspace import Client, native


def fixture(tmp_path):
    client = Client()
    revision, dataset, file_id = client.add(native())
    config = ws.retrieve(client, tmp_path, revision, dataset, file_id)
    ws.finish(client, config)
    entry = config["ledger"]["documents"][0]
    path = str(tmp_path / "configurations" / config["ledger"]["id"] / entry["path"])
    identity = {k: entry[k] for k in ("item_id", "revision_id", "item_number", "revision_label")}
    return client, path, {path: dict(identity=identity, references=[], standard_occurrences=[])}


def test_freeze_is_immutable_separate_and_retains_origin(tmp_path):
    client, path, nodes = fixture(tmp_path)
    before = ws.digest(path)
    frozen = session.freeze(client.base_url, nodes, path)
    ws.finish(client, frozen)
    entry = frozen["ledger"]["documents"][0]
    target = str(tmp_path / "configurations" / frozen["ledger"]["id"] / entry["path"])
    bound = ws.binding(target, client.base_url, False)["entry"]
    assert target != path and ws.digest(path) == before
    assert bound["local_generation_id"] and bound["dataset_id"] is None
    assert session.origin(target, client.base_url) == path
    assert bound["origin_uploaded"]
    with pytest.raises(ws.WorkspaceError):
        ws.binding(target, client.base_url)


def test_graph_order_and_cycles():
    nodes = {"parent": dict(references=[dict(target_path="child")]), "child": dict(references=[])}
    assert session.publication_order(nodes, "parent") == ["child", "parent"]
    nodes["child"]["references"] = [dict(target_path="parent")]
    with pytest.raises(ws.WorkspaceError, match="cycle"):
        session.publication_order(nodes, "parent")


def test_generation_rejects_graph_source_changes(tmp_path, monkeypatch):
    client, path, nodes = fixture(tmp_path)
    real = ws.rewrite

    def change(*a, **kw):
        result = real(*a, **kw)
        from pathlib import Path

        Path(path).chmod(0o600)
        Path(path).write_bytes(b"changed")
        return result

    monkeypatch.setattr(ws, "rewrite", change)
    with pytest.raises(ws.WorkspaceError, match="source changed"):
        session.freeze(client.base_url, nodes, path)


def test_graph_retry_keeps_original_intent_and_blocks_other_actor(tmp_path):
    client, path, nodes = fixture(tmp_path)
    client.get_checkout = lambda _: dict(user_id="actor", id="lease", version=1)
    plan = session.prepare_publication(client, nodes, path, "actor", False)
    again = session.prepare_publication(client, {}, path, "actor", False)
    assert again["operation_id"] == plan["operation_id"]
    assert again["nodes"] == nodes
    with pytest.raises(ws.WorkspaceError, match="original graph"):
        session.prepare_publication(client, nodes, path, "different-actor", False)
    with pytest.raises(ws.WorkspaceError, match="original graph"):
        session.prepare_publication(client, nodes, path, "actor", True)


def test_graph_staging_does_not_replace_original_source(tmp_path):
    client, path, nodes = fixture(tmp_path)
    client.get_checkout = lambda _: dict(user_id="actor", id="lease", version=1)
    original = ws.digest(path)
    plan = session.prepare_publication(client, nodes, path, "actor", False)
    staged = session.stage_publication(client, plan, path)
    assert staged != path
    assert ws.digest(path) == original
    assert session.stage_publication(client, plan, path) == staged


def test_graph_recovers_committed_child_without_releasing_new_lease(tmp_path):
    from test_part_checkin import case
    from uuid import uuid4

    client, path, args = case(tmp_path)
    actor = args[-1]
    value = ws.binding(path, client.base_url, False)
    identity = dict(item_id=args[3], revision_id=args[2], item_number="A1", revision_label="A")
    value["entry"].update(identity)
    ws._atomic_json(value["directory"] / ws.MANIFEST, value["ledger"])
    nodes = {str(path): dict(identity=identity, references=[], standard_occurrences=[])}
    plan = session.prepare_publication(client, nodes, str(path), actor, True)
    session.stage_publication(client, plan, str(path))
    client.lose_response = True
    with pytest.raises(Exception, match="lost response"):
        session.publish_step(client, plan, str(path), [])
    later = dict(id=str(uuid4()), version=1, user_id=actor)
    client.checkout = later
    result = session.publish_step(client, plan, str(path), [])
    assert result["status"] == "completed"
    assert client.checkout == later and len(client.sent) == 1


def test_unchanged_frozen_uploaded_source_retains_real_server_pins(tmp_path):
    client, path, nodes = fixture(tmp_path)
    original = ws.binding(path, client.base_url)["entry"]
    config = session.freeze(client.base_url, nodes, path)
    ws.finish(client, config)
    entry = config["ledger"]["documents"][0]
    frozen = str(tmp_path / "configurations" / config["ledger"]["id"] / entry["path"])
    refs = [
        dict(
            object_name="Occurrence",
            property_name="LinkedObject",
            target_path=frozen,
            target_object_name="Box",
            target_item_id=entry["item_id"],
            target_revision_id=entry["revision_id"],
        )
    ]
    pin = ws.bind_references(client, refs)[0]
    assert pin["target_file_id"] == original["file_id"]
    assert pin["target_dataset_id"] == original["dataset_id"]
    assert pin["target_file_id"] != entry["local_generation_id"]


def test_first_graph_publication_records_item_identity_on_original_working_copy(tmp_path):
    from test_part_checkin import case

    client, path, args = case(tmp_path)
    identity = dict(item_id=args[3], revision_id=args[2], item_number="A1", revision_label="A")
    nodes = {str(path): dict(identity=identity, references=[], standard_occurrences=[])}
    plan = session.prepare_publication(client, nodes, str(path), args[-1], True)
    session.stage_publication(client, plan, str(path))
    session.publish_step(client, plan, str(path), [])
    entry = ws.binding(path, client.base_url)["entry"]
    assert entry["item_id"] == args[3] and entry["revision_id"] == args[2]


def shared_parent(tmp_path, client, children):
    from uuid import uuid4
    from pathlib import Path

    path = ws.prepare_working(client.base_url, tmp_path)
    identity = dict(
        item_id=str(uuid4()), revision_id=str(uuid4()), item_number="A1", revision_label="A"
    )
    refs = []
    nodes = {}
    for index, child in enumerate(children):
        entry = ws.binding(child, client.base_url, False)["entry"]
        child_identity = {
            key: entry[key] for key in ("item_id", "revision_id", "item_number", "revision_label")
        }
        refs.append(
            dict(
                object_name="Link" + str(index),
                property_name="LinkedObject",
                target_path=child,
                target_object_name="Box",
                target_item_id=entry["item_id"],
                target_revision_id=entry["revision_id"],
            )
        )
        nodes[child] = dict(identity=child_identity, references=[], standard_occurrences=[])
    Path(path).write_bytes(
        native(links=[(r["object_name"], r["target_path"], "Box") for r in refs])
    )
    nodes[path] = dict(identity=identity, references=refs, standard_occurrences=[])
    client.get_checkout = lambda _: dict(user_id="actor", id="lease", version=1)
    return path, nodes


def test_shared_uploaded_snapshot_is_reused_across_configuration_paths(tmp_path):
    client, path, nodes = fixture(tmp_path)
    entry = ws.binding(path, client.base_url)["entry"]
    second = ws.retrieve(
        client, tmp_path, entry["revision_id"], entry["dataset_id"], entry["file_id"]
    )
    ws.finish(client, second)
    from pathlib import Path

    other = str(Path(second["directory"]) / second["ledger"]["documents"][0]["path"])
    parent, graph = shared_parent(tmp_path, client, [path, other])
    plan = session.prepare_publication(client, graph, parent, "actor", False)
    assert plan["steps"][other]["alias_of"] == path
    plan["steps"][path].update(state="complete", published_path=path)
    assert session.complete_alias(client, plan, other) == path
    staged = session.stage_publication(client, plan, parent)
    from freecad.forgepdm import fcstd

    assert all(
        (Path(staged).parent / r["file"]).resolve() == Path(path) for r in fcstd.inspect(staged)[1]
    )


def test_shared_saved_local_generation_is_published_once(tmp_path):
    client, path, nodes = fixture(tmp_path)
    working = ws.fork_working(client.base_url, path, [])
    from pathlib import Path

    Path(working).write_bytes(native(extra="<SavedEdit>changed</SavedEdit>"))
    identity = nodes[path]["identity"]
    graph = {working: dict(identity=identity, references=[], standard_occurrences=[])}
    children = []
    for _ in range(2):
        config = session.freeze(client.base_url, graph, working)
        ws.finish(client, config)
        children.append(str(Path(config["directory"]) / config["ledger"]["documents"][0]["path"]))
    parent, graph = shared_parent(tmp_path, client, children)
    plan = session.prepare_publication(client, graph, parent, "actor", False)
    assert plan["steps"][children[0]]["needs_publication"]
    assert not plan["steps"][children[1]]["needs_publication"]
    assert plan["steps"][children[1]]["alias_of"] == children[0]
