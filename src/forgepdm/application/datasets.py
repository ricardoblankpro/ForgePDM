"""Dataset upload, revision association, listing, and retrieval use cases."""

import json
import re
from datetime import datetime, timezone
from pathlib import PurePosixPath
from uuid import uuid4

from forgepdm.application.authorization import AuthorizationService
from forgepdm.application.revisions import RevisionService
from forgepdm.domain.entities import Dataset, DatasetType, File, Forbidden, NotFound, User
from forgepdm.infrastructure.database import Database
from forgepdm.infrastructure.storage import FileStorage


MEDIA_TYPE_PATTERN = re.compile(r"^[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+$")


def _safe_filename(value: str | None) -> str:
    if not value:
        raise ValueError("an original filename is required")
    candidate = PurePosixPath(value.replace("\\", "/")).name
    candidate = "".join(character for character in candidate if ord(character) >= 32 and ord(character) != 127)
    candidate = candidate.strip()
    if not candidate or candidate in {".", ".."} or len(candidate) > 255:
        raise ValueError("invalid original filename")
    return candidate


def _media_type(value: str | None) -> str:
    candidate = (value or "application/octet-stream").split(";", 1)[0].strip().lower()
    if len(candidate) > 127 or MEDIA_TYPE_PATTERN.fullmatch(candidate) is None:
        return "application/octet-stream"
    return candidate


def _file_from_row(row) -> File:
    return File(
        id=row["file_id"] if "file_id" in row.keys() else row["id"],
        content_hash=row["content_hash"],
        byte_size=row["byte_size"],
        media_type=row["media_type"],
        original_filename=row["original_filename"],
        storage_key=row["storage_key"],
        created_by=row["file_created_by"] if "file_created_by" in row.keys() else row["created_by"],
        created_at=datetime.fromisoformat(
            row["file_created_at"] if "file_created_at" in row.keys() else row["created_at"]
        ),
    )


class DatasetService:
    def __init__(
        self,
        database: Database,
        storage: FileStorage,
        authorization: AuthorizationService,
        revisions: RevisionService,
    ):
        self.database = database
        self.storage = storage
        self.authorization = authorization
        self.revisions = revisions

    def attach_file(
        self,
        *,
        user: User,
        revision_id: str,
        dataset_type: DatasetType,
        dataset_name: str,
        filename: str | None,
        media_type: str | None,
        source,
    ) -> tuple[Dataset, File]:
        safe_filename = _safe_filename(filename)
        dataset_name = dataset_name.strip()
        if not dataset_name or len(dataset_name) > 200:
            raise ValueError("dataset name must contain 1 to 200 characters")
        safe_media_type = _media_type(media_type)
        self.authorization.require_edit_revision(user, revision_id)
        self.revisions.require_checkout_owner(user, revision_id)

        staged = self.storage.stage(source)
        # Blob promotion precedes the DB commit; a failed commit can leave an orphan blob.
        storage_key = self.storage.promote(staged)
        file_id, dataset_id = str(uuid4()), str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with self.database.transaction() as connection:
            actor = connection.execute(
                "SELECT id FROM users WHERE id = ? AND enabled = 1", (user.id,)
            ).fetchone()
            if actor is None:
                raise NotFound("enabled user not found")
            self.authorization.require_edit_revision(user, revision_id, connection)
            self.revisions.require_checkout_owner(user, revision_id, connection)
            connection.execute(
                "INSERT INTO files(id, content_hash, byte_size, media_type, original_filename, storage_key, created_by, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    file_id,
                    staged.content_hash,
                    staged.byte_size,
                    safe_media_type,
                    safe_filename,
                    storage_key,
                    user.id,
                    now,
                ),
            )
            connection.execute(
                "INSERT INTO datasets(id, revision_id, dataset_type, name, created_by, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (dataset_id, revision_id, dataset_type.value, dataset_name, user.id, now),
            )
            connection.execute(
                "INSERT INTO dataset_files(dataset_id, file_id, position) VALUES (?, ?, 0)",
                (dataset_id, file_id),
            )
            connection.execute(
                "INSERT INTO audit_events(id, actor_id, event_type, entity_type, entity_id, occurred_at, details_json) "
                "VALUES (?, ?, 'dataset.file_attached', 'ItemRevision', ?, ?, ?)",
                (
                    str(uuid4()),
                    user.id,
                    revision_id,
                    now,
                    json.dumps(
                        {
                            "dataset_id": dataset_id,
                            "file_id": file_id,
                            "content_hash": staged.content_hash,
                            "byte_size": staged.byte_size,
                        }
                    ),
                ),
            )
        dataset = Dataset(
            id=dataset_id,
            revision_id=revision_id,
            dataset_type=dataset_type,
            name=dataset_name,
            file_ids=(file_id,),
            created_by=user.id,
            created_at=datetime.fromisoformat(now),
        )
        file_record = File(
            id=file_id,
            content_hash=staged.content_hash,
            byte_size=staged.byte_size,
            media_type=safe_media_type,
            original_filename=safe_filename,
            storage_key=storage_key,
            created_by=user.id,
            created_at=datetime.fromisoformat(now),
        )
        return dataset, file_record

    def list_revision(self, user: User, revision_id: str) -> list[dict]:
        with self.database.connection() as connection:
            self.authorization.require_read_revision(user, revision_id, connection)
            rows = connection.execute(
                "SELECT d.id AS dataset_id, d.revision_id, d.dataset_type, d.name AS dataset_name, "
                "d.created_by AS dataset_created_by, d.created_at AS dataset_created_at, "
                "f.id AS file_id, f.content_hash, f.byte_size, f.media_type, f.original_filename, "
                "f.storage_key, f.created_by AS file_created_by, f.created_at AS file_created_at "
                "FROM datasets d JOIN dataset_files df ON df.dataset_id = d.id "
                "JOIN files f ON f.id = df.file_id WHERE d.revision_id = ? "
                "ORDER BY d.created_at, df.position",
                (revision_id,),
            ).fetchall()
        datasets: dict[str, dict] = {}
        for row in rows:
            record = datasets.get(row["dataset_id"])
            if record is None:
                record = {
                    "id": row["dataset_id"],
                    "revision_id": row["revision_id"],
                    "dataset_type": row["dataset_type"],
                    "name": row["dataset_name"],
                    "created_by": row["dataset_created_by"],
                    "created_at": row["dataset_created_at"],
                    "files": [],
                }
                datasets[row["dataset_id"]] = record
            file_record = _file_from_row(row)
            record["files"].append(self._file_response(file_record))
        return list(datasets.values())

    def get_file(self, user: User, file_id: str) -> File:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT f.* , d.revision_id FROM files f "
                "JOIN dataset_files df ON df.file_id = f.id "
                "JOIN datasets d ON d.id = df.dataset_id WHERE f.id = ?",
                (file_id,),
            ).fetchall()
            if not rows:
                raise NotFound("file not found")
            allowed_row = None
            for row in rows:
                try:
                    self.authorization.require_read_revision(user, row["revision_id"], connection)
                except Forbidden:
                    continue
                allowed_row = row
                break
            if allowed_row is None:
                raise Forbidden("file is not available to this user")
        return _file_from_row(allowed_row)

    @staticmethod
    def _file_response(file_record: File) -> dict:
        return {
            "id": file_record.id,
            "original_filename": file_record.original_filename,
            "media_type": file_record.media_type,
            "byte_size": file_record.byte_size,
            "content_hash": file_record.content_hash,
            "download_url": f"/api/v1/files/{file_record.id}",
        }
