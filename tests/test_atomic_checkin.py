"""Atomic publication, replay, lease fencing and cross-process check-in races."""

import hashlib
import io
import multiprocessing
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from conftest import TEST_PASSWORD, create_item
from fastapi.testclient import TestClient

from forgepdm.application.checkins import CheckInService
from forgepdm.domain.entities import Conflict, Forbidden, LifecycleState, NotFound

DATA = b"part bytes"


def service(backend):
    return CheckInService(
        backend.database, backend.storage, backend.authorization, backend.revisions
    )


def intent(backend, item, user=None, **changes):
    user = user or backend.users["editor"]
    checkout = backend.revisions.current_checkout(user, item.current_revision_id)
    value = {
        "user": user,
        "revision_id": item.current_revision_id,
        "operation_id": str(uuid4()),
        "expected_checkout_id": checkout.id,
        "expected_checkout_version": checkout.version,
        "content_hash": hashlib.sha256(DATA).hexdigest(),
        "byte_size": len(DATA),
        "filename": "model.FCStd",
        "media_type": "application/octet-stream",
        "source": io.BytesIO(DATA),
    }
    value.update(changes)
    return value


def counts(backend):
    with backend.database.connection() as connection:
        return tuple(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("files", "datasets", "dataset_manifests", "checkin_operations")
        )


def test_part_checkin_publishes_one_consistent_result_and_preserves_optional_note(backend):
    item = create_item(backend)
    original = backend.items.get_item(item.id)[1].change_note
    args = intent(backend, item)
    result = service(backend).check_in(**args)
    assert counts(backend) == (1, 1, 1, 1)
    assert backend.revisions.current_checkout(args["user"], item.current_revision_id) is None
    assert backend.items.get_item(item.id)[1].change_note == original
    listed = backend.datasets.list_revision(args["user"], item.current_revision_id)
    assert listed == [result["dataset"]]
    file = result["dataset"]["files"][0]
    assert (
        backend.storage.verify(
            backend.storage.storage_key(file["content_hash"]),
            file["content_hash"],
            file["byte_size"],
        ).read_bytes()
        == DATA
    )
    with backend.database.connection() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM audit_events WHERE event_type='revision.checked_in'"
            ).fetchone()[0]
            == 1
        )
        assert connection.execute("SELECT COUNT(*) FROM dataset_references").fetchone()[0] == 0
    assert (
        service(backend).status(args["user"], item.current_revision_id, args["operation_id"])
        == result
    )


def test_replay_after_reacquiring_checkout_never_releases_new_lease(backend):
    item = create_item(backend)
    args = intent(backend, item, change_note="  Completed part  ")
    result = service(backend).check_in(**args)
    fresh = backend.revisions.acquire_checkout(args["user"], item.current_revision_id)
    assert service(backend).check_in(**dict(args, source=io.BytesIO(DATA))) == result
    assert backend.revisions.current_checkout(args["user"], item.current_revision_id).id == fresh.id
    assert counts(backend) == (1, 1, 1, 1)
    assert backend.items.get_item(item.id)[1].change_note == "Completed part"
    with pytest.raises(Conflict, match="different content or intent"):
        service(backend).check_in(
            **dict(args, source=io.BytesIO(DATA), change_note="Different note")
        )


def test_replay_after_release_returns_result_without_reopening_revision(backend):
    item = create_item(backend)
    args = intent(backend, item)
    result = service(backend).check_in(**args)
    backend.revisions.transition_lifecycle(
        args["user"], item.current_revision_id, LifecycleState.RELEASED
    )
    assert service(backend).check_in(**dict(args, source=io.BytesIO(DATA))) == result
    assert backend.items.get_item(item.id)[1].lifecycle_state == LifecycleState.RELEASED


@pytest.mark.parametrize("fault", ["hash", "size", "stream", "database"])
def test_failures_expose_no_partial_metadata_or_checkout_release(backend, fault):
    item = create_item(backend)
    args = intent(backend, item)
    if fault == "hash":
        args["content_hash"] = "0" * 64
    elif fault == "size":
        args["byte_size"] += 1
    elif fault == "stream":

        class Broken:
            def read(self, size):
                raise OSError("interrupted upload")

        args["source"] = Broken()
    else:
        with backend.database.connection() as connection:
            connection.execute(
                "CREATE TRIGGER fail_operation BEFORE INSERT ON checkin_operations BEGIN SELECT RAISE(ABORT,'injected failure'); END"
            )
    with pytest.raises((ValueError, OSError, sqlite3.IntegrityError)):
        service(backend).check_in(**args)
    assert counts(backend) == (0, 0, 0, 0)
    assert (
        backend.revisions.current_checkout(args["user"], item.current_revision_id).id
        == args["expected_checkout_id"]
    )
    assert not list((backend.storage.root / ".staging").glob("*.part"))
    with backend.database.connection() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM audit_events WHERE event_type='revision.checked_in'"
            ).fetchone()[0]
            == 0
        )
    if fault == "database":
        with backend.database.connection() as connection:
            connection.execute("DROP TRIGGER fail_operation")
        assert (
            service(backend).check_in(**dict(args, source=io.BytesIO(DATA)))["status"]
            == "completed"
        )
        assert counts(backend) == (1, 1, 1, 1)


@pytest.mark.parametrize(
    "change", ["expire", "renew", "reacquire", "other_owner", "permission", "disabled"]
)
def test_changes_during_upload_are_rechecked_inside_final_transaction(backend, change):
    item = create_item(backend)
    args = intent(backend, item)

    class ChangedStream(io.BytesIO):
        changed = False

        def read(self, size=-1):
            if not self.changed:
                self.changed = True
                if change == "renew":
                    backend.revisions.renew_checkout(args["user"], item.current_revision_id)
                elif change in ("reacquire", "other_owner"):
                    backend.revisions.release_checkout(args["user"], item.current_revision_id)
                    backend.revisions.acquire_checkout(
                        backend.users["editor2"] if change == "other_owner" else args["user"],
                        item.current_revision_id,
                    )
                else:
                    with backend.database.transaction() as connection:
                        if change == "expire":
                            connection.execute(
                                "UPDATE checkouts SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",
                                (args["expected_checkout_id"],),
                            )
                        elif change == "disabled":
                            connection.execute(
                                "UPDATE users SET enabled=0 WHERE id=?", (args["user"].id,)
                            )
                        else:
                            connection.execute(
                                "UPDATE project_memberships SET role='viewer' WHERE user_id=?",
                                (args["user"].id,),
                            )
            return super().read(size)

    with pytest.raises((Conflict, Forbidden)):
        service(backend).check_in(**dict(args, source=ChangedStream(DATA)))
    assert counts(backend) == (0, 0, 0, 0)


def test_other_actor_cannot_recover_result_and_viewers_cannot_checkin(backend):
    item = create_item(backend)
    args = intent(backend, item)
    service(backend).check_in(**args)
    with pytest.raises(NotFound):
        service(backend).status(
            backend.users["editor2"], item.current_revision_id, args["operation_id"]
        )
    assembly = create_item(backend, kind="assembly")
    with pytest.raises(Forbidden):
        service(backend).check_in(**intent(backend, assembly, user=backend.users["viewer"]))


def _process_checkin(db_path, storage_root, user, args, barrier, queue):
    from forgepdm.application.authorization import AuthorizationService
    from forgepdm.application.revisions import RevisionService
    from forgepdm.infrastructure.database import Database
    from forgepdm.infrastructure.storage import FileStorage

    database = Database(Path(db_path))
    authorization = AuthorizationService(database)
    operation = CheckInService(
        database,
        FileStorage(Path(storage_root)),
        authorization,
        RevisionService(database, authorization),
    )

    class Gate(io.BytesIO):
        started = False

        def read(self, size=-1):
            if not self.started:
                self.started = True
                barrier.wait(timeout=15)
            return super().read(size)

    try:
        queue.put(("ok", operation.check_in(user=user, source=Gate(DATA), **args)))
    except Exception as error:  # noqa: BLE001 -- relay every child-process failure to the parent test
        queue.put((type(error).__name__, str(error)))


@pytest.mark.parametrize("same_key", [True, False])
def test_two_processes_commit_once_with_same_lease(backend, same_key):
    item = create_item(backend)
    args = intent(backend, item)
    user = args.pop("user")
    args.pop("source")
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    queue = context.Queue()
    other = dict(args)
    if not same_key:
        other["operation_id"] = str(uuid4())
    processes = [
        context.Process(
            target=_process_checkin,
            args=(
                str(backend.database.path),
                str(backend.storage.root),
                user,
                value,
                barrier,
                queue,
            ),
        )
        for value in (args, other)
    ]
    for process in processes:
        process.start()
    results = [queue.get(timeout=25), queue.get(timeout=25)]
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0
    assert counts(backend) == (1, 1, 1, 1)
    if same_key:
        assert results[0][0] == results[1][0] == "ok" and results[0][1] == results[1][1]
    else:
        assert sorted(result[0] for result in results) == ["Conflict", "ok"]


def test_atomic_api_roundtrip_replay_and_status(backend, monkeypatch, tmp_path):
    monkeypatch.setenv("FORGEPDM_FILE_ROOT", str(tmp_path / "api-files"))
    from forgepdm.main import create_app

    item = create_item(backend)
    args = intent(backend, item)
    token, _, _ = backend.auth.login("editor", TEST_PASSWORD)
    headers = {"Authorization": "Bearer " + token}
    fields = {
        key: str(args[key])
        for key in (
            "operation_id",
            "expected_checkout_id",
            "expected_checkout_version",
            "content_hash",
            "byte_size",
        )
    }
    with TestClient(create_app(backend.database.path)) as client:
        endpoint = f"/api/v1/revisions/{item.current_revision_id}/checkin-native"
        first = client.post(
            endpoint,
            headers=headers,
            data=fields,
            files={"file": ("model.FCStd", DATA, "application/octet-stream")},
        )
        assert first.status_code == 200, first.text
        retry = client.post(
            endpoint,
            headers=headers,
            data=fields,
            files={"file": ("model.FCStd", DATA, "application/octet-stream")},
        )
        assert retry.json() == first.json()
        status = client.get(
            f"/api/v1/revisions/{item.current_revision_id}/checkin-operations/{args['operation_id']}",
            headers=headers,
        )
        assert status.status_code == 200 and status.json() == first.json()
        assert (
            client.post(endpoint, data=fields, files={"file": ("model.FCStd", DATA)}).status_code
            == 401
        )
        assert (
            client.get(
                f"/api/v1/revisions/{item.current_revision_id}/checkin-operations/{uuid4()}",
                headers=headers,
            ).status_code
            == 404
        )


def test_reused_key_with_different_bytes_or_false_digest_never_changes_result(backend):
    item = create_item(backend)
    args = intent(backend, item)
    result = service(backend).check_in(**args)
    other = b"other part"
    with pytest.raises(Conflict, match="different content or intent"):
        service(backend).check_in(
            **dict(
                args,
                source=io.BytesIO(other),
                content_hash=hashlib.sha256(other).hexdigest(),
                byte_size=len(other),
            )
        )
    with pytest.raises(ValueError, match="declared hash or size"):
        service(backend).check_in(**dict(args, source=io.BytesIO(other)))
    assert (
        service(backend).status(args["user"], item.current_revision_id, args["operation_id"])
        == result
    )
    assert counts(backend) == (1, 1, 1, 1)


def test_upload_limit_cleans_staging_and_preserves_lease(backend):
    from forgepdm.infrastructure.storage import UploadTooLarge

    item = create_item(backend)
    data = b"x" * 100
    args = intent(
        backend,
        item,
        source=io.BytesIO(data),
        content_hash=hashlib.sha256(data).hexdigest(),
        byte_size=len(data),
    )
    with pytest.raises(UploadTooLarge):
        service(backend).check_in(**args)
    assert counts(backend) == (0, 0, 0, 0)
    assert (
        backend.revisions.current_checkout(args["user"], item.current_revision_id).id
        == args["expected_checkout_id"]
    )
    assert not list((backend.storage.root / ".staging").glob("*.part"))


def test_additive_migration_preserves_existing_revision_checkout_and_dataset(backend):
    from forgepdm.domain.entities import DatasetType

    item = create_item(backend)
    user = backend.users["editor"]
    checkout = backend.revisions.current_checkout(user, item.current_revision_id)
    backend.datasets.attach_file(
        user=user,
        revision_id=item.current_revision_id,
        dataset_type=DatasetType.DOCUMENT,
        dataset_name="Existing file",
        filename="existing.txt",
        media_type="text/plain",
        source=io.BytesIO(DATA),
    )
    before = backend.datasets.list_revision(user, item.current_revision_id)
    with backend.database.transaction() as connection:
        connection.execute("DROP TABLE checkin_operations")
        connection.execute("DELETE FROM schema_version WHERE version=7")
        audit_before = connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
    backend.database.initialize()
    backend.database.initialize()
    assert backend.datasets.list_revision(user, item.current_revision_id) == before
    assert backend.revisions.current_checkout(user, item.current_revision_id) == checkout
    assert backend.items.get_item(item.id)[0].number == item.number
    with backend.database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM checkin_operations").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == audit_before


def reference_target(backend, kind="part", references=None):
    item = create_item(backend, kind=kind)
    result = service(backend).check_in(**intent(backend, item, references=references))
    return {
        "object_name": "Component",
        "property_name": "LinkedObject",
        "target_revision_id": item.current_revision_id,
        "target_dataset_id": result["dataset"]["id"],
        "target_file_id": result["dataset"]["files"][0]["id"],
        "target_object_name": "Assembly" if kind == "assembly" else "Box",
    }


def test_atomic_nested_assembly_pins_and_replay(backend):
    from forgepdm.application.manifests import ManifestService

    part = reference_target(backend)
    subassembly = reference_target(backend, "assembly", [part])
    parent = create_item(backend, kind="assembly")
    repeated = dict(subassembly, object_name="SecondOccurrence")
    args = intent(backend, parent, references=[repeated, subassembly])
    result = service(backend).check_in(**args)
    manifest = ManifestService(backend.database, backend.authorization, backend.revisions).get(
        args["user"], result["dataset"]["id"]
    )
    assert manifest["references"] == [subassembly, repeated]
    assert counts(backend) == (3, 3, 3, 3)
    assert (
        service(backend).check_in(
            **dict(args, source=io.BytesIO(DATA), references=[subassembly, repeated])
        )
        == result
    )
    with pytest.raises(Conflict, match="different content or intent"):
        service(backend).check_in(**dict(args, source=io.BytesIO(DATA), references=[part]))
    assert counts(backend) == (3, 3, 3, 3)


@pytest.mark.parametrize("fault", ["revision", "file", "missing", "permission", "database"])
def test_assembly_reference_failure_rolls_back_entire_publication(backend, fault):
    target = reference_target(backend)
    parent = create_item(backend, kind="assembly")
    args = intent(backend, parent, references=[dict(target)])
    before = counts(backend)
    if fault == "revision":
        args["references"][0]["target_revision_id"] = parent.current_revision_id
    elif fault == "file":
        args["references"][0]["target_file_id"] = str(uuid4())
    elif fault == "missing":
        args["references"][0]["target_dataset_id"] = str(uuid4())
    elif fault == "database":
        with backend.database.transaction() as connection:
            connection.execute(
                "CREATE TRIGGER reject_edge BEFORE INSERT ON dataset_references BEGIN SELECT RAISE(ABORT, 'injected edge failure'); END"
            )
    else:
        # Revoke access after staging starts, before the serialized final gate.
        original = backend.authorization.require_read_revision

        def deny_target(user, revision, connection=None):
            if revision == target["target_revision_id"]:
                raise Forbidden("target access revoked")
            return original(user, revision, connection)

        backend.authorization.require_read_revision = deny_target
    with pytest.raises((Conflict, NotFound, Forbidden, sqlite3.IntegrityError)):
        service(backend).check_in(**args)
    assert counts(backend) == before
    assert backend.revisions.current_checkout(args["user"], parent.current_revision_id) is not None
    with backend.database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM dataset_references").fetchone()[0] == 0


@pytest.mark.parametrize("references", [None, {}, "wrong", [1], [{"object_name": "x"}]])
def test_malformed_atomic_references_are_rejected(backend, references):
    item = create_item(backend, kind="assembly")
    if references is None:
        references = [
            {
                "object_name": "x",
                "property_name": "LinkedObject",
                "target_revision_id": 12,
                "target_dataset_id": str(uuid4()),
                "target_file_id": str(uuid4()),
                "target_object_name": "Box",
            }
        ]
    with pytest.raises(ValueError):
        service(backend).check_in(**intent(backend, item, references=references))
    assert counts(backend) == (0, 0, 0, 0)


def test_atomic_assembly_api_manifest_and_malformed_json(backend, monkeypatch, tmp_path):
    import json

    from forgepdm.main import create_app

    monkeypatch.setenv("FORGEPDM_FILE_ROOT", str(tmp_path / "api-files"))
    target = reference_target(backend)
    parent = create_item(backend, kind="assembly")
    args = intent(backend, parent)
    token, _, _ = backend.auth.login("editor", TEST_PASSWORD)
    headers = {"Authorization": "Bearer " + token}
    fields = {
        key: str(args[key])
        for key in (
            "operation_id",
            "expected_checkout_id",
            "expected_checkout_version",
            "content_hash",
            "byte_size",
        )
    }
    with TestClient(create_app(backend.database.path)) as client:
        endpoint = f"/api/v1/revisions/{parent.current_revision_id}/checkin-native-with-references"
        before = counts(backend)
        for value in ["{bad", "null", "{}", "[null]", '[{"target_revision_id":1}]']:
            response = client.post(
                endpoint,
                headers=headers,
                data=dict(fields, references_json=value),
                files={"file": ("model.FCStd", DATA)},
            )
            assert response.status_code == 422, response.text
            assert counts(backend) == before
        response = client.post(
            endpoint,
            headers=headers,
            data=dict(fields, references_json=json.dumps([target])),
            files={"file": ("model.FCStd", DATA)},
        )
        assert response.status_code == 200, response.text
        manifest = client.get(
            f"/api/v1/datasets/{response.json()['dataset']['id']}/manifest", headers=headers
        )
        assert manifest.json()["references"] == [target]
