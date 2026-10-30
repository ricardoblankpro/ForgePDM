"""Immutable CAD dataset identity, permission and migration regressions."""

from io import BytesIO

import pytest
from conftest import create_item

from forgepdm.application.manifests import ManifestService
from forgepdm.domain.entities import Conflict, DatasetType, Forbidden, ItemKind, LifecycleState


def upload(backend, item=None, user="editor"):
    item = item or create_item(backend)
    dataset, file = backend.datasets.attach_file(
        user=backend.users[user],
        revision_id=item.current_revision_id,
        dataset_type=DatasetType.NATIVE_CAD,
        dataset_name="Native",
        filename="model.FCStd",
        media_type=None,
        source=BytesIO(b"native-bytes"),
    )
    return item, dataset, file


def edge(item, dataset, file, name="Component"):
    return {
        "object_name": name,
        "property_name": "LinkedObject",
        "target_revision_id": item.current_revision_id,
        "target_dataset_id": dataset.id,
        "target_file_id": file.id,
        "target_object_name": "Box",
    }


def service(backend):
    return ManifestService(backend.database, backend.authorization, backend.revisions)


def test_manifest_binds_exact_dataset_file_and_is_immutable(backend):
    parent, data, file = upload(backend)
    child, child_data, child_file = upload(backend)
    value = edge(child, child_data, child_file)
    result = service(backend).attach(backend.users["editor"], data.id, file.id, [value])
    assert result["references"] == [value]
    assert service(backend).attach(backend.users["editor"], data.id, file.id, [value]) == result
    with pytest.raises(Conflict, match="immutable"):
        service(backend).attach(backend.users["editor"], data.id, file.id, [])
    backend.revisions.check_in(backend.users["editor"], parent.current_revision_id, "Complete")
    backend.revisions.transition_lifecycle(
        backend.users["editor"], parent.current_revision_id, LifecycleState.RELEASED
    )
    assert service(backend).get(backend.users["viewer"], data.id) == result
    with pytest.raises(Conflict):
        service(backend).attach(backend.users["editor"], data.id, file.id, [value])


def test_wrong_file_or_revision_is_rejected_atomically(backend):
    parent, data, file = upload(backend)
    child, child_data, child_file = upload(backend)
    wrong = edge(child, child_data, child_file)
    wrong["target_revision_id"] = parent.current_revision_id
    with pytest.raises(Conflict, match="different revision"):
        service(backend).attach(backend.users["editor"], data.id, file.id, [wrong])
    wrong = edge(child, child_data, file)
    with pytest.raises(Conflict, match="does not belong"):
        service(backend).attach(backend.users["editor"], data.id, file.id, [wrong])
    with backend.database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM dataset_manifests").fetchone()[0] == 0


def test_reference_cycles_and_duplicate_occurrences_are_rejected(backend):
    first, first_data, first_file = upload(backend)
    second, second_data, second_file = upload(backend)
    one = edge(second, second_data, second_file)
    with pytest.raises(ValueError, match="duplicate"):
        service(backend).attach(backend.users["editor"], first_data.id, first_file.id, [one, one])
    service(backend).attach(backend.users["editor"], first_data.id, first_file.id, [one])
    with pytest.raises(Conflict, match="cycle"):
        service(backend).attach(
            backend.users["editor"],
            second_data.id,
            second_file.id,
            [edge(first, first_data, first_file)],
        )


def test_permissions_and_checkout_are_required_in_write_transaction(backend):
    parent, data, file = upload(backend)
    with pytest.raises(Forbidden):
        service(backend).attach(backend.users["viewer"], data.id, file.id, [])
    backend.revisions.release_checkout(backend.users["editor"], parent.current_revision_id)
    with pytest.raises(Conflict, match="checkout"):
        service(backend).attach(backend.users["editor"], data.id, file.id, [])


def test_unavailable_dependencies_are_not_disclosed_by_manifest_read(backend):
    _parent, data, file = upload(backend, create_item(backend, user="admin"), user="admin")
    private = backend.items.create_item(
        kind=ItemKind.PART, name="Private", description="", created_by=backend.users["admin"].id
    )
    child, child_data, child_file = upload(backend, private, user="admin")
    service(backend).attach(
        backend.users["admin"], data.id, file.id, [edge(child, child_data, child_file)]
    )
    with pytest.raises(Forbidden):
        service(backend).get(backend.users["editor"], data.id)


def test_migration_6_preserves_existing_metadata_and_files(backend):
    item, _data, file = upload(backend)
    with backend.database.transaction() as connection:
        connection.execute("DROP TABLE dataset_references")
        connection.execute("DROP TABLE dataset_manifests")
        connection.execute("DELETE FROM schema_version WHERE version=6")
    backend.database.initialize()
    backend.database.initialize()
    assert backend.items.get_item(item.id)[0].number == item.number
    assert (
        backend.datasets.list_revision(backend.users["editor"], item.current_revision_id)[0][
            "files"
        ][0]["id"]
        == file.id
    )
    assert (
        backend.storage.verify(file.storage_key, file.content_hash, file.byte_size).read_bytes()
        == b"native-bytes"
    )


def test_concurrent_manifest_writes_cannot_replace_the_winning_graph(backend):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    _parent, data, file = upload(backend)
    child, child_data, child_file = upload(backend)
    barrier = Barrier(2)
    candidates = [[], [edge(child, child_data, child_file)]]

    def write(references):
        barrier.wait(timeout=5)
        try:
            return service(backend).attach(backend.users["editor"], data.id, file.id, references)
        except Conflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(write, candidates))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    assert service(backend).get(backend.users["editor"], data.id) == winners[0]


def test_manifest_http_validation_auth_and_immutable_conflict(backend):
    from conftest import TEST_PASSWORD
    from fastapi.testclient import TestClient

    from forgepdm.main import create_app

    _parent, data, file = upload(backend)
    app = create_app(backend.database.path)
    path = f"/api/v1/datasets/{data.id}/manifest"
    payload = {"source_file_id": file.id, "references": []}
    with TestClient(app) as client:
        assert client.get(path).status_code == 401
        token = client.post("/api/v1/auth/login", json={"username": "editor", "password": TEST_PASSWORD}).json()["access_token"]
        headers = {"Authorization": "Bearer " + token}
        assert client.get(path, headers=headers).status_code == 404
        assert client.post(path, headers=headers, json={**payload, "source_file_id": "invalid"}).status_code == 422
        assert client.post(path, headers=headers, json={**payload, "surprise": True}).status_code == 422
        assert client.post(path, headers=headers, json=payload).status_code == 201
        assert client.get(path, headers=headers).json()["source_file_id"] == file.id
        assert client.post(path, headers=headers, json={**payload, "profile": "unsupported"}).status_code == 422
        viewer = client.post("/api/v1/auth/login", json={"username": "viewer", "password": TEST_PASSWORD}).json()["access_token"]
        assert client.post(path, headers={"Authorization": "Bearer " + viewer}, json=payload).status_code == 403
