"""Immutable local CAD generations and dependency ordering, without GUI imports.

A generation is a local configuration, never a published dataset. It records
its editable origin so graph publication can resolve it to real server pins.
"""

import json
import hashlib
import shutil
from pathlib import Path
from uuid import UUID, uuid4
from types import SimpleNamespace

from . import workspace as ws


def publication_order(nodes, root):
    result, active, done = [], set(), set()

    def visit(key):
        if key in active:
            raise ws.WorkspaceError("CAD dependency cycle; publication was not started")
        if key in done:
            return
        active.add(key)
        for ref in nodes[key]["references"]:
            visit(ref["target_path"])
        active.remove(key)
        done.add(key)
        result.append(key)

    visit(root)
    return result


def freeze(server, nodes, source):
    """Freeze a GUI-captured, saved graph; validate every source before and after."""
    origin = ws.binding(source, server, require_uploaded=False)
    root = origin["root"]
    order = publication_order(nodes, source)
    stamps = {key: ws.digest(key) for key in order}
    with ws.locked(root, server):
        directory = root / "configurations" / uuid4().hex
        directory.mkdir(parents=True)
        (directory / "documents").mkdir()
        ids = {key: str(uuid4()) for key in order}
        paths = {ids[key]: directory / "documents" / (ids[key] + ".FCStd") for key in order}
        entries = []
        verified = {}
        local_client = SimpleNamespace(base_url=server, _checkpoint=lambda: None)
        fields = (
            "object_name",
            "property_name",
            "target_revision_id",
            "target_dataset_id",
            "target_file_id",
            "target_object_name",
            "target_subelement",
        )

        def signature(refs):
            return sorted(tuple(str(ref.get(field) or "") for field in fields) for ref in refs)

        for key in order:
            node = nodes[key]
            bound = ws.binding(key, server, require_uploaded=False)
            prior = bound["entry"]
            published_source = (
                prior.get("published_source", {})
                if prior.get("local_generation_id")
                else {k: prior.get(k) for k in ("dataset_id", "file_id")}
            )
            published_refs = prior.get("published_references", prior.get("references", []))
            try:
                actual_refs = ws.bind_references(local_client, node["references"])
                verified[key] = (
                    bool(published_source.get("dataset_id") and published_source.get("file_id"))
                    and stamps[key][0] == prior.get("working_hash")
                    and signature(actual_refs) == signature(published_refs)
                    and all(verified[r["target_path"]] for r in node["references"])
                )
            except ws.WorkspaceError:
                verified[key] = False
            refs = [dict(r, target_file_id=ids[r["target_path"]]) for r in node["references"]]
            destination = paths[ids[key]]
            ws.validate(key, node["references"], source_path=key)
            ws.rewrite(key, destination, refs, paths)
            entry = dict(
                prior,
                **node["identity"],
                path="documents/" + ids[key] + ".FCStd",
                file_id=ids[key],
                dataset_id=None,
                references=refs,
                local_generation_id=ids[key],
                editable_origin=prior.get("editable_origin", key),
                source_saved_hash=prior.get("source_saved_hash", stamps[key][0])
                if prior.get("local_generation_id") and stamps[key][0] == prior.get("working_hash")
                else stamps[key][0],
                published_source=published_source,
                published_references=published_refs,
                origin_uploaded=verified[key],
                standard_occurrences=node["standard_occurrences"],
            )
            entries.append(entry)
        if any(ws.digest(key) != stamps[key] for key in order):
            raise ws.WorkspaceError(
                "A source changed while freezing the local configuration; retry"
            )
        ledger = dict(
            format=1,
            id=directory.name,
            server_url=server,
            state="prepared",
            root_file_id=ids[source],
            order=[ids[key] for key in order],
            documents=entries,
        )
        ws._atomic_json(directory / ws.MANIFEST, ledger)
    return dict(directory=str(directory), ledger=ledger)


def origin(path, server):
    entry = ws.binding(path, server, require_uploaded=False)["entry"]
    return entry.get("editable_origin", path)


def baseline(path, server, item_id, revision_id):
    value = ws.binding(path, server, require_uploaded=False)
    entry = value["entry"]
    # Legacy empty working records have no trustworthy source identity.
    if (entry.get("item_id"), entry.get("revision_id")) != (item_id, revision_id):
        raise ws.WorkspaceError(
            "Working-copy provenance is missing; reopen a verified source and check out again"
        )
    return dict(
        path=str(Path(path).absolute()),
        hash=ws.digest(path)[0],
        dataset_id=entry.get("dataset_id"),
        file_id=entry.get("file_id"),
    )


def prepare_publication(client, nodes, root_path, actor_id, checkin):
    bound = ws.binding(root_path, client.base_url, require_uploaded=False)
    journal = bound["directory"] / "graph-publication.json"
    if journal.is_symlink():
        raise ws.WorkspaceError("Graph publication journal must not be linked")
    if journal.exists():
        previous = json.loads(journal.read_text())
        if previous["state"] != "complete":
            if previous.get("journal") != str(journal) or previous.get("root") != root_path:
                raise ws.WorkspaceError(
                    "Graph publication identity is corrupt; preserve its journal"
                )
            UUID(previous["operation_id"])
            if set(previous["steps"]) != set(previous["nodes"]) or previous[
                "order"
            ] != publication_order(previous["nodes"], root_path):
                raise ws.WorkspaceError(
                    "Graph publication structure is corrupt; preserve its journal"
                )
            for saved_path in previous["nodes"]:
                if ws.binding(saved_path, client.base_url, False)["root"] != bound["root"]:
                    raise ws.WorkspaceError("Graph publication escaped its workspace")
            if (previous["actor_id"], previous["server_url"], previous["checkin"]) != (
                actor_id,
                client.base_url,
                checkin,
            ):
                raise ws.WorkspaceError("Recover the original graph publication intent first")
            return previous
    order = publication_order(nodes, root_path)
    plan = dict(
        format=1,
        operation_id=str(uuid4()),
        server_url=client.base_url,
        actor_id=actor_id,
        checkin=checkin,
        state="prepared",
        root=root_path,
        journal=str(journal),
        order=order,
        nodes=nodes,
        steps={},
    )
    revisions = {}
    for path in order:
        node = nodes[path]
        value = ws.binding(path, client.base_url, require_uploaded=False)
        if value["root"] != bound["root"]:
            raise ws.WorkspaceError(
                "The assembly spans workspaces; retrieve its dependencies into one workspace before graph publication"
            )
        entry = value["entry"]
        revision = node["identity"]["revision_id"]
        published = entry.get("published_source", {}) if entry.get("local_generation_id") else entry
        unchanged = uploaded_state(client, path, node, entry)
        children = [plan["steps"][r["target_path"]] for r in node["references"]]
        if any(
            child["needs_publication"]
            or (child.get("alias_of") and plan["steps"][child["alias_of"]]["needs_publication"])
            for child in children
        ):
            unchanged = False
        edges = sorted(
            (
                r["object_name"],
                r.get("property_name", "LinkedObject"),
                r["target_object_name"],
                r.get("target_subelement", ""),
                plan["steps"][r["target_path"]]["equivalence"],
            )
            for r in node["references"]
        )
        source_hash = (
            entry.get("source_saved_hash", ws.digest(path)[0])
            if entry.get("local_generation_id") and ws.digest(path)[0] == entry.get("working_hash")
            else ws.digest(path)[0]
        )
        state = (
            ["uploaded", published.get("dataset_id"), published.get("file_id")]
            if unchanged
            else ["saved", source_hash, edges]
        )
        equivalence = hashlib.sha256(
            json.dumps([node["identity"]["item_id"], revision, state], sort_keys=True).encode()
        ).hexdigest()
        alias = revisions.get(revision)
        if alias is not None and plan["steps"][alias]["equivalence"] != equivalence:
            raise ws.WorkspaceError(
                "The assembly contains multiple configurations of one revision; resolve them before graph publication"
            )
        revisions.setdefault(revision, path)
        needs = (path == root_path or not unchanged) and alias is None
        if needs:
            checkout = client.get_checkout(revision)
            if not checkout or checkout["user_id"] != actor_id:
                raise ws.WorkspaceError(
                    "Acquire your checkout for {} before graph publication".format(
                        node["identity"]["item_number"]
                    )
                )
        plan["steps"][path] = dict(
            hash=ws.digest(path)[0],
            needs_publication=needs,
            alias_of=alias,
            equivalence=equivalence,
            working_path=None,
            published_path=None,
            published_source=published,
            checkout=dict(id=checkout["id"], version=checkout["version"]) if needs else None,
            state="pending",
        )
    frozen_dir = bound["root"] / ".forgepdm" / "graph-operations" / plan["operation_id"]
    frozen_dir.mkdir(parents=True)
    for source_path in order:
        frozen_path = frozen_dir / (uuid4().hex + ".FCStd")
        ws.validate(source_path, nodes[source_path]["references"], source_path=source_path)
        with open(source_path, "rb") as source, frozen_path.open("xb") as destination:
            shutil.copyfileobj(source, destination)
            destination.flush()
            import os

            os.fsync(destination.fileno())
        if (
            ws.digest(frozen_path)[0] != plan["steps"][source_path]["hash"]
            or ws.digest(source_path)[0] != plan["steps"][source_path]["hash"]
        ):
            raise ws.WorkspaceError(
                "A source changed while preparing publication; no upload was started"
            )
        frozen_path.chmod(0o400)
        plan["steps"][source_path]["frozen_source"] = str(frozen_path)
    ws._atomic_json(journal, plan)
    return plan


def stage_publication(client, plan, path):
    step = plan["steps"][path]
    if step["working_path"]:
        return step["working_path"]
    frozen_source = ws._safe_path(
        bound_root(plan, client.base_url),
        str(Path(step["frozen_source"]).relative_to(bound_root(plan, client.base_url))),
    )
    if ws.digest(frozen_source)[0] != step["hash"]:
        raise ws.WorkspaceError(
            "Saved source changed after publication review; recover the original graph first"
        )
    node = plan["nodes"][path]
    bound = ws.binding(path, client.base_url, require_uploaded=False)
    destination = ws.prepare_working(client.base_url, bound["root"])
    refs = []
    for r in node["references"]:
        target = plan["steps"][r["target_path"]]["published_path"]
        if target is None:
            raise ws.WorkspaceError("A child has not completed publication")
        refs.append(dict(r, target_path=target, target_file_id=str(len(refs))))
    ws.validate(path, node["references"], source_path=path)
    ws.rewrite(path, destination, refs, {r["target_file_id"]: r["target_path"] for r in refs})
    value = ws.binding(destination, client.base_url, require_uploaded=False)
    value["ledger"]["documents"][0].update(node["identity"], publication_staging=True)
    ws._atomic_json(value["directory"] / ws.MANIFEST, value["ledger"])
    step["working_path"] = destination
    ws._atomic_json(Path(plan["journal"]), plan)
    return destination


def publish_step(client, plan, path, refs, preview=None):
    from . import part_checkin

    step = plan["steps"][path]
    node = plan["nodes"][path]
    identity = node["identity"]
    current = client.get_checkout(identity["revision_id"])
    expected = step["checkout"]
    if not current or (current["id"], current["version"]) != (expected["id"], expected["version"]):
        # An existing committed per-document operation must still be recoverable.
        value = ws.binding(step["working_path"], client.base_url, False)
        operation = part_checkin._load(
            value, client, identity["revision_id"], identity["item_id"], plan["actor_id"]
        )
        recovered = None
        if operation is not None and (
            operation["expected_checkout_id"],
            operation["expected_checkout_version"],
        ) == (expected["id"], expected["version"]):
            if (
                client.part_checkin_status(identity["revision_id"], operation["operation_id"])
                is not None
            ):
                recovered = part_checkin._resolve(client, value, operation)
        if recovered is None:
            raise ws.WorkspaceError(
                "Checkout changed after graph review; recover or review the graph again"
            )
        result = recovered
    else:
        result = part_checkin.checkin(
            client,
            step["working_path"],
            identity["revision_id"],
            identity["item_id"],
            plan["actor_id"],
            refs,
            preview=preview,
            keep_checkout=not plan["checkin"],
        )
    value = ws.binding(path, client.base_url, require_uploaded=False)
    record = result["dataset"]["files"][0]
    if ws.digest(path)[0] == step["hash"]:
        entry = value["entry"]
        entry.update(
            **identity,
            working_hash=step["hash"],
            origin_uploaded=True,
            published_source=dict(dataset_id=result["dataset"]["id"], file_id=record["id"]),
            published_references=[
                {k: v for k, v in ref.items() if k != "target_path"}
                for ref in ws.bind_references(client, refs)
            ],
        )
        if not entry.get("local_generation_id"):
            entry.update(dataset_id=result["dataset"]["id"], file_id=record["id"])
        ws._atomic_json(value["directory"] / ws.MANIFEST, value["ledger"])
    step.update(state="published", published_path=None, result=result)
    ws._atomic_json(Path(plan["journal"]), plan)
    return result


def acknowledge_graph(plan):
    plan["state"] = "complete"
    ws._atomic_json(Path(plan["journal"]), plan)
    return plan


def bound_root(plan, server):
    return ws.binding(plan["root"], server, False)["root"]


def record_published_configuration(client, plan, path, snapshot_path):
    step = plan["steps"][path]
    entry = ws.binding(snapshot_path, client.base_url)["entry"]
    result = step["result"]["dataset"]
    if (entry["dataset_id"], entry["file_id"]) != (
        result["id"],
        result["files"][0]["id"],
    ) or ws.digest(snapshot_path)[0] != entry["working_hash"]:
        raise ws.WorkspaceError(
            "Published configuration differs from the completed graph operation"
        )
    step.update(state="complete", published_path=snapshot_path, immutable_source=True)
    ws._atomic_json(Path(plan["journal"]), plan)
    return snapshot_path


def unpublished_origin(path, server, editing_path):
    entry = ws.binding(path, server, require_uploaded=False)["entry"]
    return bool(
        entry.get("local_generation_id")
        and not entry.get("origin_uploaded")
        and entry.get("editable_origin") == editing_path
    )


def uploaded_state(client, path, node, entry):
    published = entry.get("published_source", {}) if entry.get("local_generation_id") else entry
    if (
        not published.get("dataset_id")
        or not published.get("file_id")
        or ws.digest(path)[0] != entry.get("working_hash")
    ):
        return False
    if entry.get("local_generation_id") and not entry.get("origin_uploaded"):
        return False
    try:
        actual = ws.bind_references(client, node["references"])
    except ws.WorkspaceError:
        return False
    fields = (
        "object_name",
        "property_name",
        "target_revision_id",
        "target_dataset_id",
        "target_file_id",
        "target_object_name",
        "target_subelement",
    )

    def signature(refs):
        return sorted(tuple(str(r.get(field) or "") for field in fields) for r in refs)

    return signature(actual) == signature(
        entry.get("published_references", entry.get("references", []))
    )


def complete_alias(client, plan, path):
    step = plan["steps"][path]
    canonical = plan["steps"][step["alias_of"]]
    if canonical["state"] != "complete":
        raise ws.WorkspaceError("Shared dependency has not completed publication")
    value = ws.binding(path, client.base_url, False)
    source = ws.binding(canonical["published_path"], client.base_url, False)["entry"]
    published = source.get("published_source", {}) if source.get("local_generation_id") else source
    if not published.get("dataset_id") or not published.get("file_id"):
        raise ws.WorkspaceError("Shared dependency has no verified published snapshot")
    if ws.digest(path)[0] == step["hash"]:
        entry = value["entry"]
        entry.update(
            origin_uploaded=True,
            working_hash=step["hash"],
            published_source={k: published[k] for k in ("dataset_id", "file_id")},
            published_references=source.get("published_references", source.get("references", [])),
        )
        if not entry.get("local_generation_id"):
            entry.update(dataset_id=published["dataset_id"], file_id=published["file_id"])
        ws._atomic_json(value["directory"] / ws.MANIFEST, value["ledger"])
    step.update(state="complete", published_path=canonical["published_path"], immutable_source=True)
    ws._atomic_json(Path(plan["journal"]), plan)
    return canonical["published_path"]


def publication_requirements(client, nodes, root_path):
    result = {}
    for path in publication_order(nodes, root_path):
        entry = ws.binding(path, client.base_url, False)["entry"]
        result[path] = (
            path == root_path
            or not uploaded_state(client, path, nodes[path], entry)
            or any(result[r["target_path"]] for r in nodes[path]["references"])
        )
    return result
