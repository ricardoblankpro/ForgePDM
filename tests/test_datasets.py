from io import BytesIO

import pytest

from forgepdm.domain.entities import Conflict, DatasetType, Forbidden
from forgepdm.infrastructure.storage import BlobIntegrityError, UploadTooLarge

from conftest import create_item


def test_upload_associates_revision_dataset_and_download_verifies_hash(backend):
    item = create_item(backend)
    dataset, file_record = backend.datasets.attach_file(
        user=backend.users["editor"],
        revision_id=item.current_revision_id,
        dataset_type=DatasetType.NATIVE_CAD,
        dataset_name="Native model",
        filename="../../design\\bracket.FCStd",
        media_type="application/octet-stream",
        source=BytesIO(b"cad-file-content"),
    )

    assert dataset.file_ids == (file_record.id,)
    assert file_record.original_filename == "bracket.FCStd"
    assert file_record.byte_size == len(b"cad-file-content")
    assert backend.storage.verify(
        file_record.storage_key, file_record.content_hash, file_record.byte_size
    ).read_bytes() == b"cad-file-content"
    assert backend.datasets.get_file(backend.users["editor"], file_record.id) == file_record
    listed = backend.datasets.list_revision(backend.users["editor"], item.current_revision_id)
    assert listed[0]["id"] == dataset.id
    assert listed[0]["files"][0]["content_hash"] == file_record.content_hash

    blob_path = backend.storage.root / file_record.storage_key
    blob_path.write_bytes(b"tampered")
    with pytest.raises(BlobIntegrityError):
        backend.storage.verify(file_record.storage_key, file_record.content_hash, file_record.byte_size)


def test_upload_limit_and_checkout_are_enforced_without_database_rows(backend):
    item = create_item(backend)
    with pytest.raises(UploadTooLarge):
        backend.datasets.attach_file(
            user=backend.users["editor"],
            revision_id=item.current_revision_id,
            dataset_type=DatasetType.OTHER,
            dataset_name="Too big",
            filename="large.bin",
            media_type="application/octet-stream",
            source=BytesIO(b"x" * 17),
        )
    with backend.database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM datasets").fetchone()[0] == 0
    assert list((backend.storage.root / ".staging").iterdir()) == []

    backend.revisions.release_checkout(backend.users["editor"], item.current_revision_id)
    with pytest.raises(Conflict):
        backend.datasets.attach_file(
            user=backend.users["editor"],
            revision_id=item.current_revision_id,
            dataset_type=DatasetType.OTHER,
            dataset_name="No lease",
            filename="part.bin",
            media_type=None,
            source=BytesIO(b"small"),
        )


def test_dataset_upload_requires_revision_access(backend):
    item = create_item(backend)
    with pytest.raises(Forbidden):
        backend.datasets.attach_file(
            user=backend.users["viewer"],
            revision_id=item.current_revision_id,
            dataset_type=DatasetType.OTHER,
            dataset_name="Denied",
            filename="part.bin",
            media_type=None,
            source=BytesIO(b"small"),
        )
