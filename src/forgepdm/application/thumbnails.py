"""Immutable, optional image derivatives of exact native CAD files."""

import hashlib
from datetime import datetime, timezone
from io import BytesIO
from uuid import uuid4

from PIL import Image, PngImagePlugin, UnidentifiedImageError

from forgepdm.domain.entities import Conflict, Forbidden, NotFound
from forgepdm.infrastructure.storage import FileStorage

MAX_BYTES = 1024 * 1024
MAX_DIMENSION = 512
PROFILE = "isometric-v1"

# This backend's only Pillow use is bounded thumbnail ingest. Apply fixed limits
# once, never mutate decoder policy while individual requests are running.
PngImagePlugin.MAX_TEXT_CHUNK = 64 * 1024
PngImagePlugin.MAX_TEXT_MEMORY = MAX_BYTES


def normalized_png(raw):
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("thumbnail must contain at most 1 MiB of PNG bytes")
    try:
        with Image.open(BytesIO(raw), formats=["PNG"]) as image:
            width, height = image.size
            if not (1 <= width <= MAX_DIMENSION and 1 <= height <= MAX_DIMENSION):
                raise ValueError("thumbnail dimensions must not exceed 512 by 512")
            if getattr(image, "n_frames", 1) != 1:
                raise ValueError("animated thumbnails are not supported")
            image.verify()
        with Image.open(BytesIO(raw), formats=["PNG"]) as image:
            image.load()
            rgba = image.convert("RGBA")
            clean = Image.new("RGB", image.size, "white")
            clean.paste(rgba, mask=rgba.getchannel("A"))
            output = BytesIO()
            clean.save(output, format="PNG")
        encoded = output.getvalue()
        if len(encoded) > MAX_BYTES:
            raise ValueError("normalized thumbnail exceeds 1 MiB")
        return encoded, width, height
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as error:
        raise ValueError("thumbnail must be a valid bounded PNG image") from error


class ThumbnailService:
    def __init__(self, database, storage, authorization):
        self.database, self.storage, self.authorization = database, storage, authorization

    def _source(self, connection, user, file_id, *, write=False):
        source = connection.execute(
            "SELECT f.*,d.revision_id FROM files f "
            "JOIN dataset_files df ON df.file_id=f.id JOIN datasets d ON d.id=df.dataset_id "
            "WHERE f.id=? AND d.dataset_type='native_cad'",
            (file_id,),
        ).fetchone()
        if source is None:
            raise NotFound("native CAD file not found")
        self.authorization.require_read_revision(user, source["revision_id"], connection)
        if write:
            actor = connection.execute(
                "SELECT enabled FROM users WHERE id=?", (user.id,)
            ).fetchone()
            if actor is None or not actor["enabled"]:
                raise Forbidden("an enabled uploader is required")
            self.authorization.require_manage_revision(user, source["revision_id"], connection)
            if user.role != "admin" and source["created_by"] != user.id:
                raise Forbidden(
                    "only the source uploader or an administrator may attach its preview"
                )
        return source

    def _existing(self, connection, file_id):
        return connection.execute(
            "SELECT t.*,f.content_hash,f.byte_size,f.storage_key FROM file_thumbnails t "
            "JOIN files f ON f.id=t.image_file_id WHERE t.source_file_id=?",
            (file_id,),
        ).fetchone()

    @staticmethod
    def _response(row):
        return {
            "source_file_id": row["source_file_id"],
            "source_content_hash": row["source_content_hash"],
            "content_hash": row["content_hash"],
            "byte_size": row["byte_size"],
            "render_profile": row["render_profile"],
            "width": row["width"],
            "height": row["height"],
        }

    def get(self, user, file_id):
        with self.database.connection() as connection:
            source = self._source(connection, user, file_id)
            row = self._existing(connection, file_id)
            if row is None:
                raise NotFound("no thumbnail is available for this snapshot")
            if row["source_content_hash"] != source["content_hash"]:
                raise Conflict("thumbnail source identity is inconsistent")
        path = self.storage.verify(row["storage_key"], row["content_hash"], row["byte_size"])
        return path, self._response(row)

    def attach(self, user, file_id, source_hash, raw, profile=PROFILE):
        if profile != PROFILE:
            raise ValueError("unsupported thumbnail render profile")
        if not raw or len(raw) > MAX_BYTES:
            raise ValueError("thumbnail must contain at most 1 MiB of PNG bytes")
        input_hash = hashlib.sha256(raw).hexdigest()

        def existing_or_validate(connection):
            source = self._source(connection, user, file_id, write=True)
            if source["content_hash"] != source_hash:
                raise Conflict("thumbnail does not describe the declared source file")
            row = self._existing(connection, file_id)
            if row and (row["input_hash"], row["render_profile"]) != (input_hash, profile):
                raise Conflict("this source snapshot already has a different immutable thumbnail")
            return source, row

        with self.database.connection() as connection:
            _, existing = existing_or_validate(connection)
            if existing:
                return self._response(existing)
        encoded, width, height = normalized_png(raw)
        # Small images have their own bound, independent of the CAD upload limit.
        staged = FileStorage(self.storage.root, MAX_BYTES).stage(BytesIO(encoded))
        key = self.storage.promote(staged)
        with self.database.transaction() as connection:
            source, existing = existing_or_validate(connection)
            if existing:
                return self._response(existing)
            identifier, now = str(uuid4()), datetime.now(timezone.utc).isoformat()
            connection.execute(
                "INSERT INTO files(id,content_hash,byte_size,media_type,original_filename,storage_key,created_by,created_at) "
                "VALUES (?,?,?,'image/png','isometric.png',?,?,?)",
                (identifier, staged.content_hash, staged.byte_size, key, user.id, now),
            )
            connection.execute(
                "INSERT INTO file_thumbnails(source_file_id,source_content_hash,image_file_id,input_hash,render_profile,width,height,created_by,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    file_id,
                    source["content_hash"],
                    identifier,
                    input_hash,
                    profile,
                    width,
                    height,
                    user.id,
                    now,
                ),
            )
            connection.execute(
                "INSERT INTO audit_events(id,actor_id,event_type,entity_type,entity_id,occurred_at,details_json) "
                "VALUES (?,?,'file.thumbnail_attached','File',?,?,'{}')",
                (str(uuid4()), user.id, file_id, now),
            )
            return self._response(self._existing(connection, file_id))
