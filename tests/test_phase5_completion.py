"""Stale legacy writes, recoverable revisions, process races and storage diagnosis."""

import io
import multiprocessing
import sqlite3
from uuid import uuid4

import pytest
from conftest import TEST_PASSWORD, create_item
from fastapi.testclient import TestClient

from forgepdm.application.manifests import ManifestService
from forgepdm.application.recovery import recovery_report
from forgepdm.application.revisions import RevisionService
from forgepdm.domain.entities import Conflict, DatasetType, Forbidden, LifecycleState, NotFound


def token(b, item):
    checkout = b.revisions.current_checkout(b.users["editor"], item.current_revision_id)
    return {"expected_checkout_id": checkout.id, "expected_checkout_version": checkout.version}


def upload(b, item, **extra):
    return b.datasets.attach_file(
        user=b.users["editor"],
        revision_id=item.current_revision_id,
        dataset_type=DatasetType.NATIVE_CAD,
        dataset_name="Native",
        filename="part.FCStd",
        media_type=None,
        source=io.BytesIO(b"native bytes"),
        **extra,
    )


def released(b):
    item = create_item(b)
    b.revisions.check_in(b.users["editor"], item.current_revision_id)
    b.revisions.transition_lifecycle(
        b.users["editor"], item.current_revision_id, LifecycleState.RELEASED
    )
    return item


@pytest.mark.parametrize("change", ["renew", "reacquire", "other_user", "expire"])
def test_upload_rechecks_exact_lease_after_streaming(backend, monkeypatch, change):
    b = backend
    item = create_item(b)
    expected = token(b, item)
    original = b.storage.stage

    def stage(source):
        result = original(source)
        if change == "renew":
            b.revisions.renew_checkout(b.users["editor"], item.current_revision_id)
        elif change in ("reacquire", "other_user"):
            b.revisions.release_checkout(b.users["editor"], item.current_revision_id)
            b.revisions.acquire_checkout(
                b.users["editor2" if change == "other_user" else "editor"], item.current_revision_id
            )
        else:
            with b.database.transaction() as c:
                c.execute(
                    "UPDATE checkouts SET expires_at='2000-01-01' WHERE id=?",
                    (expected["expected_checkout_id"],),
                )
        return result

    monkeypatch.setattr(b.storage, "stage", stage)
    with pytest.raises(Conflict):
        upload(b, item, **expected)
    with b.database.connection() as c:
        assert c.execute("SELECT COUNT(*) FROM datasets").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 0
    report = recovery_report(b.database, b.storage)
    assert len(report["unreferenced_candidates"]) == 1
    assert not report["referenced_file_errors"]


@pytest.mark.parametrize("write", ["manifest", "checkin"])
def test_delayed_same_user_write_cannot_use_new_checkout(backend, write):
    b = backend
    item = create_item(b)
    expected = token(b, item)
    dataset, file = upload(b, item, **expected)
    b.revisions.release_checkout(b.users["editor"], item.current_revision_id)
    fresh = b.revisions.acquire_checkout(b.users["editor"], item.current_revision_id)
    with pytest.raises(Conflict, match="checkout changed"):
        if write == "manifest":
            ManifestService(b.database, b.authorization, b.revisions).attach(
                b.users["editor"], dataset.id, file.id, [], **expected
            )
        else:
            b.revisions.check_in(b.users["editor"], item.current_revision_id, **expected)
    assert b.revisions.current_checkout(b.users["editor"], item.current_revision_id) == fresh


def test_public_legacy_routes_reject_missing_tokens_and_replay_revision(
    backend, monkeypatch, tmp_path
):
    b = backend
    monkeypatch.setenv("FORGEPDM_FILE_ROOT", str(b.storage.root))
    from forgepdm.main import create_app

    item = create_item(b)
    access, _, _ = b.auth.login("editor", TEST_PASSWORD)
    headers = {"Authorization": "Bearer " + access}
    expected = token(b, item)
    dataset, file = upload(b, item)
    with TestClient(create_app(b.database.path)) as client:
        path = f"/api/v1/revisions/{item.current_revision_id}"
        assert client.post(path + "/checkin", headers=headers).status_code == 422
        assert (
            client.post(
                path + "/datasets",
                headers=headers,
                data={"dataset_type": "native_cad"},
                files={"file": ("part.FCStd", b"bytes")},
            ).status_code
            == 422
        )
        assert (
            client.post(
                f"/api/v1/datasets/{dataset.id}/manifest",
                headers=headers,
                json={"source_file_id": file.id},
            ).status_code
            == 422
        )
        assert (
            client.post(path + "/checkin/fenced", headers=headers, json=expected).status_code == 204
        )
        assert (
            client.post(
                path + "/lifecycle", headers=headers, json={"target": "released"}
            ).status_code
            == 204
        )
        intent = {
            "operation_id": str(uuid4()),
            "expected_source_revision_id": item.current_revision_id,
            "change_note": "next",
        }
        endpoint = f"/api/v1/items/{item.id}/revisions/recoverable"
        first = client.post(endpoint, headers=headers, json=intent)
        assert first.status_code == 201, first.text
        assert client.post(endpoint, headers=headers, json=intent).json() == first.json()
        status = f"/api/v1/items/{item.id}/revision-operations/{intent['operation_id']}"
        assert client.get(status, headers=headers).json() == first.json()
        assert (
            client.post(
                endpoint, headers=headers, json={**intent, "change_note": "different"}
            ).status_code
            == 409
        )


def test_revision_replay_preserves_original_result_and_new_checkout(backend):
    b = backend
    item = released(b)
    intent = {"operation_id": str(uuid4()), "expected_source_revision_id": item.current_revision_id}
    first = b.revisions.create_next_revision(b.users["editor"], item.id, "Next", **intent)
    b.revisions.release_checkout(b.users["editor"], first[0].id)
    fresh = b.revisions.acquire_checkout(b.users["editor"], first[0].id)
    assert b.revisions.create_next_revision(b.users["editor"], item.id, "Next", **intent) == first
    assert b.revisions.current_checkout(b.users["editor"], first[0].id) == fresh
    with pytest.raises(NotFound):
        b.revisions.revision_operation(b.users["editor2"], item.id, intent["operation_id"])
    with pytest.raises(Conflict):
        b.revisions.create_next_revision(b.users["editor"], item.id, "Other", **intent)
    with pytest.raises(Conflict, match="source revision changed"):
        b.revisions.create_next_revision(
            b.users["editor"],
            item.id,
            "Next",
            operation_id=str(uuid4()),
            expected_source_revision_id=item.current_revision_id,
        )
    with b.database.transaction() as c:
        c.execute("DELETE FROM project_memberships WHERE user_id=?", (b.users["editor"].id,))
    with pytest.raises(Forbidden):
        b.revisions.revision_operation(b.users["editor"], item.id, intent["operation_id"])


def test_revision_creation_rollback_and_migration_preservation(backend):
    b = backend
    item = released(b)
    with b.database.transaction() as c:
        c.execute(
            "CREATE TRIGGER fail_operation BEFORE INSERT ON revision_operations BEGIN SELECT RAISE(ABORT, 'injected'); END"
        )
    intent = {"operation_id": str(uuid4()), "expected_source_revision_id": item.current_revision_id}
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        b.revisions.create_next_revision(b.users["editor"], item.id, "Next", **intent)
    assert b.items.get_item(item.id)[0].current_revision_id == item.current_revision_id
    with b.database.transaction() as c:
        assert (
            c.execute("SELECT COUNT(*) FROM item_revisions WHERE item_id=?", (item.id,)).fetchone()[
                0
            ]
            == 1
        )
        c.execute("DROP TRIGGER fail_operation")
        c.execute("DROP TABLE revision_operations")
        c.execute("DELETE FROM schema_version WHERE version=17")
    b.database.initialize()
    b.database.initialize()
    assert b.items.get_item(item.id)[0].current_revision_id == item.current_revision_id
    assert (
        b.revisions.create_next_revision(b.users["editor"], item.id, "Next", **intent)[0].label
        == "B"
    )


def _revision_worker(database_path, user, item_id, source_id, operation_id, ready, start, results):
    from forgepdm.application.authorization import AuthorizationService
    from forgepdm.infrastructure.database import Database

    database = Database(database_path)
    service = RevisionService(database, AuthorizationService(database))
    ready.put(True)
    start.wait(15)
    try:
        revision, checkout = service.create_next_revision(
            user, item_id, "Next", operation_id=operation_id, expected_source_revision_id=source_id
        )
        results.put(("ok", revision.id, checkout.id))
    except Conflict:
        results.put(("conflict",))


@pytest.mark.parametrize("same_key", [True, False])
def test_revision_creation_independent_process_races(backend, same_key):
    b = backend
    item = released(b)
    ctx = multiprocessing.get_context("spawn")
    ready, results, start = ctx.Queue(), ctx.Queue(), ctx.Event()
    operation_id = str(uuid4())
    processes = [
        ctx.Process(
            target=_revision_worker,
            args=(
                b.database.path,
                b.users["editor"],
                item.id,
                item.current_revision_id,
                operation_id if same_key or i == 0 else str(uuid4()),
                ready,
                start,
                results,
            ),
        )
        for i in range(2)
    ]
    try:
        for process in processes:
            process.start()
        for _ in processes:
            ready.get(timeout=20)
        start.set()
        outcomes = [results.get(timeout=20) for _ in processes]
        if same_key:
            assert outcomes[0] == outcomes[1] and outcomes[0][0] == "ok"
        else:
            assert sorted(value[0] for value in outcomes) == ["conflict", "ok"]
        for process in processes:
            process.join(10)
            assert process.exitcode == 0
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(10)
    with b.database.connection() as c:
        assert (
            c.execute("SELECT COUNT(*) FROM item_revisions WHERE item_id=?", (item.id,)).fetchone()[
                0
            ]
            == 2
        )
        assert c.execute("SELECT COUNT(*) FROM revision_operations").fetchone()[0] == 1


def test_recovery_reports_corruption_staging_and_missing_manifest_without_deleting(backend):
    b = backend
    item = create_item(b)
    dataset, file = upload(b, item)
    staged = b.storage.stage(io.BytesIO(b"interrupted"))
    blob = b.storage.root / file.storage_key
    blob.write_bytes(b"corrupted")
    before = {p: p.read_bytes() for p in b.storage.root.rglob("*") if p.is_file()}
    report = recovery_report(b.database, b.storage)
    assert report["database_integrity"] == ["ok"]
    assert report["native_datasets_without_manifest"] == [dataset.id]
    assert report["referenced_file_errors"][0]["file_id"] == file.id
    assert staged.path.relative_to(b.storage.root).as_posix() in report["unreferenced_candidates"]
    assert before == {p: p.read_bytes() for p in b.storage.root.rglob("*") if p.is_file()}
