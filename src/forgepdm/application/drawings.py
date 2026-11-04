"""Explicit immutable PDF publications tied to exact native CAD snapshots."""

import hashlib
import json
import re
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4
from zipfile import BadZipFile, ZipFile

from forgepdm.application.datasets import _safe_filename
from forgepdm.domain.entities import Conflict, Forbidden, NotFound
from forgepdm.infrastructure.storage import UploadTooLarge

MAX_PDF_BYTES = 25 * 1024**2
MAX_BUNDLE_BYTES = 100 * 1024**2


class LimitedReader:
    def __init__(self, source, limit):
        self.source, self.limit, self.size = source, limit, 0

    def read(self, size=-1):
        value = self.source.read(min(size if size >= 0 else self.limit + 1, self.limit + 1))
        self.size += len(value)
        if self.size > self.limit:
            raise UploadTooLarge("drawing publication exceeds its size limit")
        return value


class DrawingService:
    def __init__(self, database, storage, authorization, revisions):
        self.database, self.storage = database, storage
        self.authorization, self.revisions = authorization, revisions

    @staticmethod
    def normalize(intent):
        keys = {
            "operation_id",
            "source_dataset_id",
            "source_file_id",
            "source_content_hash",
            "expected_checkout_id",
            "expected_checkout_version",
            "pages",
        }
        if not isinstance(intent, dict) or set(intent) != keys:
            raise ValueError("invalid drawing publication fields")
        intent = json.loads(json.dumps(intent))
        for key in ("operation_id", "source_dataset_id", "source_file_id", "expected_checkout_id"):
            if not isinstance(intent[key], str):
                raise TypeError("drawing operation/source/checkout IDs must be UUID strings")
            intent[key] = str(UUID(intent[key]))
        version = intent["expected_checkout_version"]
        if type(version) is not int or version < 1:
            raise ValueError("checkout version must be a positive integer")

        def digest(value):
            if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise ValueError("invalid drawing SHA-256 hash")

        digest(intent["source_content_hash"])
        pages = intent["pages"]
        if not isinstance(pages, list) or not 1 <= len(pages) <= 32:
            raise ValueError("publish between 1 and 32 drawing pages")
        names = set()
        for page in pages:
            if not isinstance(page, dict) or set(page) != {
                "page_name",
                "page_label",
                "filename",
                "content_hash",
                "byte_size",
            }:
                raise ValueError("invalid drawing page fields")
            if (
                not isinstance(page["page_name"], str)
                or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,99}", page["page_name"]) is None
                or page["page_name"] in names
            ):
                raise ValueError("choose distinct native TechDraw page names")
            names.add(page["page_name"])
            if (
                not isinstance(page["page_label"], str)
                or not 1 <= len(page["page_label"]) <= 200
                or not page["page_label"].strip()
            ):
                raise ValueError("page label must contain 1 to 200 characters")
            if not isinstance(page["filename"], str):
                raise TypeError("a PDF filename is required")
            page["filename"] = _safe_filename(page["filename"])
            if not page["filename"].lower().endswith(".pdf"):
                raise ValueError("drawing filename must end in .pdf")
            digest(page["content_hash"])
            if type(page["byte_size"]) is not int or not 1 <= page["byte_size"] <= MAX_PDF_BYTES:
                raise ValueError("PDF size must be between 1 byte and 25 MiB")
        if sum(page["byte_size"] for page in pages) > MAX_BUNDLE_BYTES:
            raise ValueError("drawing PDFs exceed 100 MiB")
        return intent

    def _source(self, connection, revision_id, intent):
        row = connection.execute(
            "SELECT f.content_hash,d.created_at FROM datasets d JOIN dataset_files df ON df.dataset_id=d.id "
            "JOIN files f ON f.id=df.file_id WHERE d.id=? AND f.id=? AND d.revision_id=? "
            "AND d.dataset_type='native_cad'",
            (intent["source_dataset_id"], intent["source_file_id"], revision_id),
        ).fetchone()
        if row is None or row["content_hash"] != intent["source_content_hash"]:
            raise Conflict("source must be the exact native snapshot of this revision")
        return row

    def _gate(self, connection, user, revision_id, intent):
        actor = connection.execute(
            "SELECT enabled,role,must_change_password FROM users WHERE id=?", (user.id,)
        ).fetchone()
        if actor is None or not actor["enabled"] or actor["must_change_password"]:
            raise Forbidden("an enabled user with a current password is required")
        user = replace(user, role=actor["role"])
        self.authorization.require_edit_revision(user, revision_id, connection)
        lease = self.revisions.require_checkout_owner(user, revision_id, connection)
        if (lease.id, lease.version) != (
            intent["expected_checkout_id"],
            intent["expected_checkout_version"],
        ):
            raise Conflict("checkout changed; prepare a new drawing publication")
        return self._source(connection, revision_id, intent)

    def _existing(self, connection, user, operation_id, fingerprint):
        row = connection.execute(
            "SELECT fingerprint,result_json FROM drawing_publications WHERE created_by=? AND operation_id=?",
            (user.id, operation_id),
        ).fetchone()
        if row:
            if row["fingerprint"] != fingerprint:
                raise Conflict("drawing operation ID already used with different content or intent")
            return json.loads(row["result_json"])
        return None

    def status(self, user, revision_id, operation_id):
        with self.database.connection() as connection:
            self.authorization.require_read_revision(user, revision_id, connection)
            row = connection.execute(
                "SELECT result_json FROM drawing_publications WHERE created_by=? AND operation_id=? AND revision_id=?",
                (user.id, operation_id, revision_id),
            ).fetchone()
        if row is None:
            raise NotFound("drawing publication operation not found")
        return json.loads(row["result_json"])

    def publish(self, user, revision_id, intent, source):
        # Input is normalized by the API model; avoid allowing a caller to mutate it.
        intent = self.normalize(intent)
        fingerprint = hashlib.sha256(
            json.dumps(
                dict(revision_id=revision_id, **intent), sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        with self.database.connection() as connection:
            self.authorization.require_read_revision(user, revision_id, connection)
            if self._existing(connection, user, intent["operation_id"], fingerprint) is None:
                self._gate(connection, user, revision_id, intent)
        bundle = self.storage.stage(LimitedReader(source, MAX_BUNDLE_BYTES + 65536))
        staged = []
        try:
            with ZipFile(bundle.path) as archive:
                infos = archive.infolist()
                expected = [f"page_{index:04d}.pdf" for index in range(1, len(intent["pages"]) + 1)]
                if [entry.filename for entry in infos] != expected:
                    raise ValueError("drawing bundle members do not match the reviewed page order")
                if sum(entry.file_size for entry in infos) > MAX_BUNDLE_BYTES:
                    raise UploadTooLarge("drawing PDFs exceed the total size limit")
                for info, page in zip(infos, intent["pages"], strict=True):
                    if (
                        info.is_dir()
                        or info.file_size != page["byte_size"]
                        or info.file_size > MAX_PDF_BYTES
                    ):
                        raise ValueError("PDF member size differs from the declared page")
                    with archive.open(info) as stream:
                        blob = self.storage.stage(LimitedReader(stream, MAX_PDF_BYTES))
                    staged.append(blob)
                    if (blob.content_hash, blob.byte_size) != (
                        page["content_hash"],
                        page["byte_size"],
                    ):
                        raise ValueError("PDF bytes differ from the reviewed page hash/size")
                    with blob.path.open("rb") as stream:
                        head = stream.read(5)
                        stream.seek(max(0, blob.byte_size - 1024))
                        tail = stream.read()
                    if head != b"%PDF-" or b"%%EOF" not in tail:
                        raise ValueError("page is not a complete PDF document")
            keys = [self.storage.promote(blob) for blob in staged]
            for key, blob in zip(keys, staged, strict=True):
                self.storage.verify(key, blob.content_hash, blob.byte_size)
            with self.database.transaction() as connection:
                self.authorization.require_read_revision(user, revision_id, connection)
                existing = self._existing(connection, user, intent["operation_id"], fingerprint)
                if existing is not None:
                    return existing
                source_record = self._gate(connection, user, revision_id, intent)
                identifier, now = str(uuid4()), datetime.now(UTC)
                pages = []
                for index, (page, blob, key) in enumerate(
                    zip(intent["pages"], staged, keys, strict=True), 1
                ):
                    dataset_id, file_id = str(uuid4()), str(uuid4())
                    connection.execute(
                        "INSERT INTO files(id,content_hash,byte_size,media_type,original_filename,storage_key,created_by,created_at) VALUES (?,?,?,'application/pdf',?,?,?,?)",
                        (
                            file_id,
                            blob.content_hash,
                            blob.byte_size,
                            page["filename"],
                            key,
                            user.id,
                            now.isoformat(),
                        ),
                    )
                    connection.execute(
                        "INSERT INTO datasets(id,revision_id,dataset_type,name,created_by,created_at) VALUES (?,?,'drawing',?,?,?)",
                        (dataset_id, revision_id, page["page_label"], user.id, now.isoformat()),
                    )
                    connection.execute(
                        "INSERT INTO dataset_files(dataset_id,file_id,position) VALUES (?,?,0)",
                        (dataset_id, file_id),
                    )
                    pages.append(
                        {
                            "page_name": page["page_name"],
                            "page_label": page["page_label"],
                            "position": index,
                            "dataset_id": dataset_id,
                            "file_id": file_id,
                            "filename": page["filename"],
                            "content_hash": blob.content_hash,
                            "byte_size": blob.byte_size,
                        }
                    )
                result = {
                    "id": identifier,
                    "operation_id": intent["operation_id"],
                    "revision_id": revision_id,
                    "source_dataset_id": intent["source_dataset_id"],
                    "source_file_id": intent["source_file_id"],
                    "source_content_hash": intent["source_content_hash"],
                    "source_created_at": source_record["created_at"],
                    "created_at": now.isoformat(),
                    "pages": pages,
                }
                connection.execute(
                    "INSERT INTO drawing_publications(id,revision_id,source_dataset_id,source_file_id,created_by,created_at,operation_id,fingerprint,result_json) VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        identifier,
                        revision_id,
                        intent["source_dataset_id"],
                        intent["source_file_id"],
                        user.id,
                        now.isoformat(),
                        intent["operation_id"],
                        fingerprint,
                        json.dumps(result),
                    ),
                )
                for page in pages:
                    connection.execute(
                        "INSERT INTO drawing_pages(publication_id,dataset_id,file_id,page_name,page_label,position) VALUES (?,?,?,?,?,?)",
                        (
                            identifier,
                            page["dataset_id"],
                            page["file_id"],
                            page["page_name"],
                            page["page_label"],
                            page["position"],
                        ),
                    )
                self.revisions._audit(
                    connection,
                    user.id,
                    "drawing.published",
                    "ItemRevision",
                    revision_id,
                    now,
                    {
                        "publication_id": identifier,
                        "source_dataset_id": intent["source_dataset_id"],
                        "source_file_id": intent["source_file_id"],
                        "page_count": len(pages),
                    },
                )
                return result
        except (BadZipFile, RuntimeError) as error:
            raise ValueError("drawing bundle is not a readable PDF archive") from error
        finally:
            bundle.path.unlink(missing_ok=True)
            for blob in staged:
                blob.path.unlink(missing_ok=True)

    def list_revision(self, user, revision_id):
        with self.database.connection() as connection:
            connection.execute("BEGIN")
            self.authorization.require_read_revision(user, revision_id, connection)
            latest = connection.execute(
                "SELECT d.id AS dataset_id,f.id AS file_id FROM datasets d JOIN dataset_files df ON df.dataset_id=d.id JOIN files f ON f.id=df.file_id WHERE d.revision_id=? AND d.dataset_type='native_cad' ORDER BY d.created_at DESC,d.id DESC,f.id DESC LIMIT 1",
                (revision_id,),
            ).fetchone()
            rows = connection.execute(
                "SELECT p.result_json,u.display_name FROM drawing_publications p JOIN users u ON u.id=p.created_by WHERE p.revision_id=? ORDER BY p.created_at DESC,p.id DESC",
                (revision_id,),
            ).fetchall()
        result = []
        for row in rows:
            value = json.loads(row["result_json"])
            value["published_by"] = row["display_name"]
            value["newer_snapshot_available"] = latest is not None and (
                value["source_dataset_id"],
                value["source_file_id"],
            ) != (latest["dataset_id"], latest["file_id"])
            result.append(value)
        return result
