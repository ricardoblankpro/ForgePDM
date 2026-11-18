"""Exact-source immutable previews inherit permissions and survive backup/restore."""

import base64
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image, PngImagePlugin
from test_manifests import upload

from forgepdm.application import backups
from forgepdm.application.thumbnails import ThumbnailService, normalized_png
from forgepdm.domain.entities import Conflict, Forbidden, LifecycleState, NotFound
from forgepdm.infrastructure.database import Database
from forgepdm.infrastructure.storage import BlobIntegrityError, FileStorage


def png(color="red", size=(384, 384), **kwargs):
    out = BytesIO()
    Image.new("RGB", size, color).save(out, format="PNG", **kwargs)
    return out.getvalue()


def service(backend):
    return ThumbnailService(backend.database, backend.storage, backend.authorization)


def test_exact_source_immutable_idempotency_and_no_cad_or_checkout_changes(backend):
    b = backend
    item, _, file = upload(b)
    other_item, _, other_file = upload(b)
    before = b.storage.verify(file.storage_key, file.content_hash, file.byte_size).read_bytes()
    checkout = b.revisions.current_checkout(b.users["editor"], item.current_revision_id)
    images = service(b)
    image = png()
    result = images.attach(b.users["editor"], file.id, file.content_hash, image)
    assert result == images.attach(b.users["editor"], file.id, file.content_hash, image)
    assert result["source_file_id"] == file.id and result["width"] == 384
    assert b.revisions.current_checkout(b.users["editor"], item.current_revision_id) == checkout
    assert (
        b.storage.verify(file.storage_key, file.content_hash, file.byte_size).read_bytes() == before
    )
    with pytest.raises(Conflict):
        images.attach(b.users["editor"], file.id, file.content_hash, png("blue"))
    with pytest.raises(Conflict):
        images.attach(b.users["editor"], other_file.id, "a" * 64, image)
    with pytest.raises(NotFound):
        images.get(b.users["viewer"], other_file.id)
    with b.database.connection() as c:
        assert c.execute("SELECT COUNT(*) FROM file_thumbnails").fetchone()[0] == 1


def test_authorized_reader_and_uploader_only_derivative_after_checkin_and_release(backend):
    b = backend
    item, _, file = upload(b)
    images = service(b)
    for user in ("viewer", "editor2"):
        with pytest.raises(Forbidden):
            images.attach(b.users[user], file.id, file.content_hash, png())
    b.revisions.check_in(b.users["editor"], item.current_revision_id)
    b.revisions.transition_lifecycle(
        b.users["editor"], item.current_revision_id, LifecycleState.RELEASED
    )
    images.attach(b.users["editor"], file.id, file.content_hash, png())
    assert images.get(b.users["viewer"], file.id)[1]["source_content_hash"] == file.content_hash
    with b.database.transaction() as c:
        c.execute("DELETE FROM project_memberships WHERE user_id=?", (b.users["viewer"].id,))
    with pytest.raises(Forbidden):
        images.get(b.users["viewer"], file.id)


@pytest.mark.parametrize(
    "raw", [b"", b"not PNG", b"x" * (1024 * 1024 + 1), png(size=(513, 2)), png()[:60]]
)
def test_invalid_or_oversized_image_never_creates_metadata(backend, raw):
    b = backend
    _, _, file = upload(b)
    with pytest.raises(ValueError):
        service(b).attach(b.users["editor"], file.id, file.content_hash, raw)
    with b.database.connection() as c:
        assert c.execute("SELECT COUNT(*) FROM file_thumbnails").fetchone()[0] == 0


def test_metadata_stripped_animation_rejected_and_corruption_detected(backend):
    b = backend
    _, _, file = upload(b)
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("Private", "untrusted metadata")
    raw = png(pnginfo=metadata)
    encoded, _, _ = normalized_png(raw)
    with Image.open(BytesIO(encoded)) as image:
        assert not image.info
    animated = png(save_all=True, append_images=[Image.new("RGB", (384, 384), "blue")])
    with pytest.raises(ValueError, match="animated"):
        normalized_png(animated)
    images = service(b)
    images.attach(b.users["editor"], file.id, file.content_hash, raw)
    path, _ = images.get(b.users["viewer"], file.id)
    path.write_bytes(b"corrupt")
    with pytest.raises(BlobIntegrityError):
        images.get(b.users["viewer"], file.id)


def test_racing_same_intent_creates_one_image_and_one_association(backend):
    b = backend
    _, _, file = upload(b)
    images, raw = service(b), png()

    def attach(_):
        return images.attach(b.users["editor"], file.id, file.content_hash, raw)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attach, range(2)))
    assert results[0] == results[1]
    with b.database.connection() as c:
        assert c.execute("SELECT COUNT(*) FROM file_thumbnails").fetchone()[0] == 1
        assert c.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 2


def test_backup_restore_includes_image_bytes_and_accepts_pre_thumbnail_schema(backend, tmp_path):
    b = backend
    _, _, file = upload(b)
    service(b).attach(b.users["editor"], file.id, file.content_hash, png())
    report = backups.create_backup(b.database, b.storage, tmp_path / "backups")
    assert report["file_records"] == 2 and report["schema_version"] == 20
    restored = tmp_path / "restored"
    backups.restore_backup(
        report["backup"], restored, live_database=b.database.path, live_storage=b.storage.root
    )
    from forgepdm.application.authorization import AuthorizationService

    db = Database(restored / "database.sqlite3")
    restored_service = ThumbnailService(
        db, FileStorage(restored / "files"), AuthorizationService(db)
    )
    assert restored_service.get(b.users["viewer"], file.id)[0].is_file()
    with b.database.transaction() as c:
        c.execute("DROP TABLE description_consolidation")
        c.execute("DELETE FROM schema_version WHERE version=20")
        c.execute("DROP TABLE localized_translation_versions")
        c.execute("DROP TABLE localized_source_versions")
        c.execute("DROP TABLE localized_text_sources")
        c.execute("ALTER TABLE items DROP COLUMN source_language")
        c.execute("DELETE FROM schema_version WHERE version=19")
        c.execute("DROP TABLE file_thumbnails")
        c.execute("DELETE FROM schema_version WHERE version=18")
    legacy = backups.create_backup(b.database, b.storage, tmp_path / "legacy-backups")
    assert backups.verify_backup(legacy["backup"])["schema_version"] == 17


def test_authorized_api_has_bounded_bytes_identity_headers_and_no_anonymous_images(
    backend, monkeypatch
):
    b = backend
    _, _, file = upload(b)
    monkeypatch.setenv("FORGEPDM_FILE_ROOT", str(b.storage.root))
    from forgepdm.api.v1.routes import current_user
    from forgepdm.main import create_app

    app = create_app(b.database.path)
    path = f"/api/v1/files/{file.id}/thumbnail"
    with TestClient(app) as client:
        assert client.get(path).status_code == 401
        app.dependency_overrides[current_user] = lambda: b.users["viewer"]
        assert client.get(path).status_code == 404
        payload = {
            "source_content_hash": file.content_hash,
            "png_base64": base64.b64encode(png()).decode(),
        }
        assert client.post(path, json=payload).status_code == 404
        app.dependency_overrides[current_user] = lambda: b.users["editor"]
        assert client.post(path, json=payload).status_code == 201
        assert client.post(path, json=payload).status_code == 201
        payload["png_base64"] = "not valid base64!!!"
        assert client.post(path, json=payload).status_code == 422
        app.dependency_overrides[current_user] = lambda: b.users["viewer"]
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.headers["x-forgepdm-source-hash"] == file.content_hash
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
