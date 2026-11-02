"""Atomic metadata publication for a fenced, replayable native check-in."""

import hashlib
import json
import re
from uuid import UUID, uuid4

from forgepdm.application import revisions as revision_clock
from forgepdm.application.datasets import _media_type, _safe_filename
from forgepdm.application.manifests import REFERENCE_FIELDS, ManifestService
from forgepdm.domain.entities import Conflict, Forbidden, NotFound


class CheckInService:
    def __init__(self, database, storage, authorization, revisions):
        self.database = database
        self.storage = storage
        self.authorization = authorization
        self.revisions = revisions

    def _existing(self, connection, user, operation_id, fingerprint):
        row = connection.execute(
            "SELECT fingerprint, result_json FROM checkin_operations WHERE actor_id=? AND operation_id=?",
            (user.id, operation_id),
        ).fetchone()
        if row is None:
            return None
        if row["fingerprint"] != fingerprint:
            raise Conflict(
                "check-in operation ID was already used with different content or intent"
            )
        return json.loads(row["result_json"])

    def _fence(self, connection, user, revision_id, checkout_id, checkout_version):
        actor = connection.execute("SELECT enabled FROM users WHERE id=?", (user.id,)).fetchone()
        if actor is None or not actor["enabled"]:
            raise Forbidden("an enabled user is required")
        self.authorization.require_edit_revision(user, revision_id, connection)
        checkout = self.revisions.require_checkout_owner(user, revision_id, connection)
        if checkout.id != checkout_id or checkout.version != checkout_version:
            raise Conflict("checkout changed; the original check-in lease is no longer valid")
        return checkout

    def status(self, user, revision_id, operation_id):
        operation_id = str(UUID(operation_id))
        with self.database.connection() as connection:
            self.authorization.require_read_revision(user, revision_id, connection)
            row = connection.execute(
                "SELECT result_json FROM checkin_operations WHERE actor_id=? AND operation_id=? AND revision_id=?",
                (user.id, operation_id, revision_id),
            ).fetchone()
        if row is None:
            raise NotFound("check-in operation not found")
        return json.loads(row["result_json"])

    def check_in(
        self,
        *,
        user,
        revision_id,
        operation_id,
        expected_checkout_id,
        expected_checkout_version,
        content_hash,
        byte_size,
        filename,
        media_type,
        source,
        change_note="",
        references=None,
    ):
        operation_id = str(UUID(operation_id))
        revision_id = str(UUID(revision_id))
        checkout_id = str(UUID(expected_checkout_id))
        if type(expected_checkout_version) is not int or expected_checkout_version < 1:
            raise ValueError("checkout version must be a positive integer")
        if type(byte_size) is not int or byte_size <= 0:
            raise ValueError("byte size must be positive")
        if re.fullmatch(r"[0-9a-f]{64}", content_hash) is None:
            raise ValueError("invalid SHA-256 content hash")
        filename, media_type = _safe_filename(filename), _media_type(media_type)
        change_note = change_note.strip()
        if len(change_note) > 2000:
            raise ValueError("check-in note must contain at most 2000 characters")
        references = ManifestService._references([] if references is None else references)
        intent = {
            "revision_id": revision_id,
            "checkout_id": checkout_id,
            "checkout_version": expected_checkout_version,
            "content_hash": content_hash,
            "byte_size": byte_size,
            "filename": filename,
            "media_type": media_type,
            "change_note": change_note,
        }
        if references:
            intent["references"] = references
        fingerprint = hashlib.sha256(
            json.dumps(intent, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        # Preflight avoids staging for invalid requests. The final gate is authoritative.
        with self.database.connection() as connection:
            self.authorization.require_read_revision(user, revision_id, connection)
            existing = self._existing(connection, user, operation_id, fingerprint)
            if existing is None:
                self._fence(connection, user, revision_id, checkout_id, expected_checkout_version)
        staged = self.storage.stage(source)
        if (staged.content_hash, staged.byte_size) != (content_hash, byte_size):
            staged.path.unlink(missing_ok=True)
            raise ValueError("uploaded bytes differ from the declared hash or size")
        storage_key = self.storage.promote(staged)
        self.storage.verify(storage_key, content_hash, byte_size)
        with self.database.transaction() as connection:
            self.authorization.require_read_revision(user, revision_id, connection)
            existing = self._existing(connection, user, operation_id, fingerprint)
            if existing is not None:
                return existing
            checkout = self._fence(
                connection, user, revision_id, checkout_id, expected_checkout_version
            )
            ManifestService.validate_targets(connection, user, self.authorization, references)
            now = revision_clock._now()
            timestamp = now.isoformat()
            dataset_id, file_id = str(uuid4()), str(uuid4())
            connection.execute(
                "INSERT INTO files(id,content_hash,byte_size,media_type,original_filename,storage_key,created_by,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    file_id,
                    content_hash,
                    byte_size,
                    media_type,
                    filename,
                    storage_key,
                    user.id,
                    timestamp,
                ),
            )
            connection.execute(
                "INSERT INTO datasets(id,revision_id,dataset_type,name,created_by,created_at) VALUES (?,?,'native_cad','Native CAD',?,?)",
                (dataset_id, revision_id, user.id, timestamp),
            )
            connection.execute(
                "INSERT INTO dataset_files(dataset_id,file_id,position) VALUES (?,?,0)",
                (dataset_id, file_id),
            )
            connection.execute(
                "INSERT INTO dataset_manifests(dataset_id,source_file_id,profile,created_by,created_at) VALUES (?,?,'freecad-app-link-v1',?,?)",
                (dataset_id, file_id, user.id, timestamp),
            )
            for reference in references:
                connection.execute(
                    "INSERT INTO dataset_references(id,dataset_id,object_name,property_name,"
                    "target_revision_id,target_dataset_id,target_file_id,target_object_name) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (str(uuid4()), dataset_id, *(reference[field] for field in REFERENCE_FIELDS)),
                )
            connection.execute(
                "UPDATE item_revisions SET change_note=CASE WHEN ?='' THEN change_note ELSE ? END, modified_at=? WHERE id=?",
                (change_note, change_note, timestamp, revision_id),
            )
            connection.execute(
                "UPDATE checkouts SET released_at=?,release_reason='checked in',version=version+1 WHERE id=?",
                (timestamp, checkout.id),
            )
            for event, entity, identifier, details in [
                (
                    "dataset.file_attached",
                    "ItemRevision",
                    revision_id,
                    {
                        "dataset_id": dataset_id,
                        "file_id": file_id,
                        "content_hash": content_hash,
                        "byte_size": byte_size,
                    },
                ),
                (
                    "dataset.manifest_attached",
                    "Dataset",
                    dataset_id,
                    {"source_file_id": file_id, "references": len(references)},
                ),
                (
                    "revision.checked_in",
                    "ItemRevision",
                    revision_id,
                    {
                        "change_note": change_note,
                        "operation_id": operation_id,
                        "checkout_id": checkout.id,
                        "checkout_version": checkout.version,
                    },
                ),
            ]:
                self.revisions._audit(connection, user.id, event, entity, identifier, now, details)
            result = {
                "operation_id": operation_id,
                "revision_id": revision_id,
                "status": "completed",
                "checkout_id": checkout.id,
                "checkout_version": checkout.version,
                "dataset": {
                    "id": dataset_id,
                    "revision_id": revision_id,
                    "dataset_type": "native_cad",
                    "name": "Native CAD",
                    "created_by": user.id,
                    "created_at": timestamp,
                    "files": [
                        {
                            "id": file_id,
                            "original_filename": filename,
                            "media_type": media_type,
                            "content_hash": content_hash,
                            "byte_size": byte_size,
                            "download_url": f"/api/v1/files/{file_id}",
                        }
                    ],
                },
            }
            connection.execute(
                "INSERT INTO checkin_operations(actor_id,operation_id,revision_id,fingerprint,result_json,created_at) VALUES (?,?,?,?,?,?)",
                (
                    user.id,
                    operation_id,
                    revision_id,
                    fingerprint,
                    json.dumps(result, sort_keys=True),
                    timestamp,
                ),
            )
            return result
