"""Derived drawings must retain exact sources, fenced writes and retry safety."""

import hashlib
import io
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4
from zipfile import ZipFile

import pytest
from conftest import TEST_PASSWORD, create_item
from fastapi.testclient import TestClient

from forgepdm.application.drawings import DrawingService
from forgepdm.domain.entities import Conflict, DatasetType, Forbidden, LifecycleState, NotFound
from forgepdm.infrastructure.storage import FileStorage

PDF = b"%PDF-1.4\nfixture page\n%%EOF\n"


def bundle(contents):
    stream = io.BytesIO()
    with ZipFile(stream, "w") as archive:
        for index, data in enumerate(contents, 1):
            archive.writestr(f"page_{index:04d}.pdf", data)
    stream.seek(0)
    return stream


@pytest.fixture
def drawing_case(backend):
    item = create_item(backend)
    user = backend.users["editor"]
    dataset, source = backend.datasets.attach_file(
        user=user,
        revision_id=item.current_revision_id,
        dataset_type=DatasetType.NATIVE_CAD,
        dataset_name="Native CAD",
        filename="model.FCStd",
        media_type="application/octet-stream",
        source=io.BytesIO(b"cad"),
    )
    lease = backend.revisions.current_checkout(user, item.current_revision_id)
    intent = {
        "operation_id": str(uuid4()),
        "source_dataset_id": dataset.id,
        "source_file_id": source.id,
        "source_content_hash": source.content_hash,
        "expected_checkout_id": lease.id,
        "expected_checkout_version": lease.version,
        "pages": [
            {
                "page_name": "Page",
                "page_label": "Drawing",
                "filename": "drawing.pdf",
                "content_hash": hashlib.sha256(PDF).hexdigest(),
                "byte_size": len(PDF),
            }
        ],
    }
    service = DrawingService(
        backend.database,
        FileStorage(backend.storage.root),
        backend.authorization,
        backend.revisions,
    )
    return service, item.current_revision_id, intent, user


def test_publication_is_source_pinned_drawing_dataset_and_does_not_release_checkout(
    backend, drawing_case
):
    service, revision, intent, user = drawing_case
    result = service.publish(user, revision, intent, bundle([PDF]))
    assert result["source_file_id"] == intent["source_file_id"]
    assert backend.revisions.current_checkout(user, revision).id == intent["expected_checkout_id"]
    datasets = backend.datasets.list_revision(user, revision)
    assert [row["dataset_type"] for row in datasets].count("drawing") == 1
    row = service.list_revision(backend.users["viewer"], revision)[0]
    assert not row["newer_snapshot_available"] and row["published_by"] == "Editor"
    assert row["pages"][0]["content_hash"] == hashlib.sha256(PDF).hexdigest()


def test_replay_after_lease_release_returns_same_result_without_duplicates(backend, drawing_case):
    service, revision, intent, user = drawing_case
    first = service.publish(user, revision, intent, bundle([PDF]))
    backend.revisions.check_in(user, revision)
    assert service.publish(user, revision, intent, bundle([PDF])) == first
    assert service.status(user, revision, intent["operation_id"]) == first
    assert len(service.list_revision(user, revision)) == 1
    with pytest.raises(NotFound):
        service.status(backend.users["viewer"], revision, intent["operation_id"])
    changed = deepcopy(intent)
    changed["pages"][0]["page_label"] = "different intent"
    with pytest.raises(Conflict):
        service.publish(user, revision, changed, bundle([PDF]))


@pytest.mark.parametrize(
    "fault", ["other_owner", "viewer", "source_pair", "source_hash", "lease_version", "released"]
)
def test_publication_rejects_unauthorized_or_changed_source_and_checkout(
    backend, drawing_case, fault
):
    service, revision, intent, user = drawing_case
    if fault in ("viewer", "other_owner"):
        user = backend.users["viewer" if fault == "viewer" else "editor2"]
    elif fault == "source_pair":
        intent["source_file_id"] = str(uuid4())
    elif fault == "source_hash":
        intent["source_content_hash"] = "0" * 64
    elif fault == "lease_version":
        intent["expected_checkout_version"] += 1
    else:
        backend.revisions.check_in(user, revision)
        backend.revisions.transition_lifecycle(user, revision, LifecycleState.RELEASED)
    with pytest.raises((Conflict, Forbidden)):
        service.publish(user, revision, intent, bundle([PDF]))
    assert service.list_revision(backend.users["admin"], revision) == []


def test_final_gate_rechecks_lease_after_staging_and_rolls_back_whole_set(
    backend, drawing_case, monkeypatch
):
    service, revision, intent, user = drawing_case
    intent["pages"].append(dict(intent["pages"][0], page_name="Second", filename="second.pdf"))
    promote = service.storage.promote
    revoked = False

    def revoke(blob):
        nonlocal revoked
        if not revoked:
            backend.revisions.check_in(user, revision)
            revoked = True
        return promote(blob)

    monkeypatch.setattr(service.storage, "promote", revoke)
    with pytest.raises(Conflict):
        service.publish(user, revision, intent, bundle([PDF, PDF]))
    assert not service.list_revision(user, revision)
    assert all(
        row["dataset_type"] != "drawing" for row in backend.datasets.list_revision(user, revision)
    )


def test_atomic_metadata_rollback_after_first_pdf_insert(backend, drawing_case, monkeypatch):
    service, revision, intent, user = drawing_case
    intent["pages"].append(dict(intent["pages"][0], page_name="Second"))
    with backend.database.transaction() as connection:
        connection.execute(
            "CREATE TRIGGER reject_drawing_page BEFORE INSERT ON drawing_pages BEGIN SELECT RAISE(ABORT, 'injected metadata failure'); END"
        )
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        service.publish(user, revision, intent, bundle([PDF, PDF]))
    assert not service.list_revision(user, revision)
    assert all(
        row["dataset_type"] != "drawing" for row in backend.datasets.list_revision(user, revision)
    )


@pytest.mark.parametrize(
    "fault",
    [
        "truncated",
        "wrong_hash",
        "missing_member",
        "extra_member",
        "bad_zip",
        "duplicate_name",
        "zero_pages",
    ],
)
def test_bad_or_changed_pdf_bundle_publishes_nothing(backend, drawing_case, fault):
    service, revision, intent, user = drawing_case
    contents = [PDF]
    if fault == "truncated":
        contents = [b"%PDF-1.4\nmissing EOF"]
        intent["pages"][0].update(
            byte_size=len(contents[0]), content_hash=hashlib.sha256(contents[0]).hexdigest()
        )
    elif fault == "wrong_hash":
        intent["pages"][0]["content_hash"] = "0" * 64
    elif fault == "missing_member":
        contents = []
    elif fault == "extra_member":
        contents.append(PDF)
    elif fault == "duplicate_name":
        intent["pages"].append(intent["pages"][0])
    elif fault == "zero_pages":
        intent["pages"] = []
    stream = io.BytesIO(b"not zip") if fault == "bad_zip" else bundle(contents)
    with pytest.raises(ValueError):
        service.publish(user, revision, intent, stream)
    assert service.list_revision(user, revision) == []


def test_later_native_upload_marks_pdf_old_without_changing_its_source(backend, drawing_case):
    service, revision, intent, user = drawing_case
    service.publish(user, revision, intent, bundle([PDF]))
    backend.datasets.attach_file(
        user=user,
        revision_id=revision,
        dataset_type=DatasetType.NATIVE_CAD,
        dataset_name="newer",
        filename="model.FCStd",
        media_type="application/octet-stream",
        source=io.BytesIO(b"new"),
    )
    row = service.list_revision(user, revision)[0]
    assert row["newer_snapshot_available"] and row["source_file_id"] == intent["source_file_id"]


def test_role_revocation_during_staging_does_not_keep_stale_admin_access(
    backend, drawing_case, monkeypatch
):
    service, revision, intent, user = drawing_case
    stale_admin = replace(user, role="admin")
    promote = service.storage.promote

    def revoke(blob):
        with backend.database.transaction() as connection:
            connection.execute("DELETE FROM project_memberships WHERE user_id=?", (user.id,))
        return promote(blob)

    monkeypatch.setattr(service.storage, "promote", revoke)
    with pytest.raises(Forbidden):
        service.publish(stale_admin, revision, intent, bundle([PDF]))


def test_drawing_api_authorizes_preview_bytes_and_hides_private_sources(
    backend, drawing_case, monkeypatch, tmp_path
):
    service, revision, intent, user = drawing_case
    monkeypatch.setenv("FORGEPDM_DATABASE", str(backend.database.path))
    monkeypatch.setenv("FORGEPDM_FILE_ROOT", str(service.storage.root))
    import json

    from forgepdm.main import create_app

    with TestClient(create_app(backend.database.path)) as client:
        endpoint = f"/api/v1/revisions/{revision}/drawings"
        assert client.get(endpoint).status_code == 401
        token = client.post(
            "/api/v1/auth/login", json={"username": "editor", "password": TEST_PASSWORD}
        ).json()["access_token"]
        headers = {"Authorization": "Bearer " + token}
        response = client.post(
            endpoint,
            headers=headers,
            data={"intent_json": json.dumps(intent)},
            files={"file": ("drawings.zip", bundle([PDF]), "application/zip")},
        )
        assert response.status_code == 201, response.text
        file_id = response.json()["pages"][0]["file_id"]
        pdf = client.get(f"/api/v1/files/{file_id}", headers=headers)
        assert pdf.content == PDF and pdf.headers["content-type"] == "application/pdf"
        with backend.database.transaction() as connection:
            connection.execute("DELETE FROM project_memberships WHERE user_id=?", (user.id,))
        assert client.get(endpoint, headers=headers).status_code == 404
        assert client.get(f"/api/v1/files/{file_id}", headers=headers).status_code == 404


def test_migration_nine_preserves_existing_accounts_native_files_and_checkout(
    backend, drawing_case
):
    def records():
        with backend.database.connection() as connection:
            return {
                table: [tuple(row) for row in connection.execute("SELECT * FROM " + table)]
                for table in (
                    "users",
                    "projects",
                    "auth_sessions",
                    "items",
                    "item_revisions",
                    "files",
                    "datasets",
                    "checkouts",
                )
            }

    before = records()
    with backend.database.transaction() as connection:
        connection.execute("DROP TABLE drawing_pages")
        connection.execute("DROP TABLE drawing_publications")
        connection.execute("DELETE FROM schema_version WHERE version=9")
    backend.database.initialize()
    assert records() == before


@pytest.mark.parametrize(
    "fault", ["page_count", "pdf_size", "total_size", "label_size", "unsafe_zip_path"]
)
def test_drawing_publication_bounds_are_enforced_before_metadata_changes(drawing_case, fault):
    service, revision, intent, user = drawing_case
    if fault == "page_count":
        intent["pages"] = [
            dict(intent["pages"][0], page_name=f"Page{index}") for index in range(33)
        ]
    elif fault == "pdf_size":
        intent["pages"][0]["byte_size"] = 25 * 1024**2 + 1
    elif fault == "total_size":
        intent["pages"] = [
            dict(intent["pages"][0], page_name=f"Page{index}", byte_size=25 * 1024**2)
            for index in range(5)
        ]
    elif fault == "label_size":
        intent["pages"][0]["page_label"] = " " * 201 + "X"
    stream = bundle([PDF])
    if fault == "unsafe_zip_path":
        stream = io.BytesIO()
        with ZipFile(stream, "w") as archive:
            archive.writestr("../drawing.pdf", PDF)
        stream.seek(0)
    with pytest.raises(ValueError):
        service.publish(user, revision, intent, stream)
    assert service.list_revision(user, revision) == []


def test_concurrent_retries_publish_one_complete_page_set(drawing_case):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    service, revision, intent, user = drawing_case
    intent["pages"].append(dict(intent["pages"][0], page_name="Second", filename="second.pdf"))
    barrier = Barrier(2)

    def publish():
        barrier.wait(timeout=5)
        return service.publish(user, revision, intent, bundle([PDF, PDF]))

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = [
            future.result(timeout=10)
            for future in [executor.submit(publish), executor.submit(publish)]
        ]
    assert first == second and len(first["pages"]) == 2
    assert len(service.list_revision(user, revision)) == 1
