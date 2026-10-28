"""Immutable content-addressed filesystem storage."""

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4


CHUNK_SIZE = 1024 * 1024
DEFAULT_MAX_UPLOAD_BYTES = 1024 * 1024 * 1024


class StorageError(Exception):
    """Base class for blob storage errors."""


class UploadTooLarge(StorageError):
    """The upload exceeded the configured maximum size."""


class EmptyUpload(StorageError):
    """Zero byte files are not accepted."""


class BlobNotFound(StorageError):
    """The database references a blob that is missing from storage."""


class BlobIntegrityError(StorageError):
    """Stored bytes do not match their recorded hash or size."""


@dataclass(frozen=True, slots=True)
class StagedBlob:
    path: Path
    content_hash: str
    byte_size: int


class FileStorage:
    def __init__(self, root: Path, max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES):
        if max_upload_bytes <= 0:
            raise ValueError("max_upload_bytes must be positive")
        self.root = root
        self.max_upload_bytes = max_upload_bytes

    @staticmethod
    def storage_key(content_hash: str) -> str:
        if re.fullmatch(r"[0-9a-f]{64}", content_hash) is None:
            raise ValueError("invalid SHA-256 content hash")
        return f"sha256/{content_hash[:2]}/{content_hash[2:4]}/{content_hash}"

    def stage(self, source: BinaryIO) -> StagedBlob:
        staging = self.root / ".staging"
        staging.mkdir(parents=True, exist_ok=True)
        staged_path = staging / f"{uuid4().hex}.part"
        digest = hashlib.sha256()
        size = 0
        try:
            with staged_path.open("xb") as staged_file:
                while True:
                    chunk = source.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > self.max_upload_bytes:
                        raise UploadTooLarge("upload exceeds the configured size limit")
                    digest.update(chunk)
                    staged_file.write(chunk)
                if size == 0:
                    raise EmptyUpload("empty files are not accepted")
                staged_file.flush()
                os.fsync(staged_file.fileno())
            return StagedBlob(staged_path, digest.hexdigest(), size)
        except BaseException:
            staged_path.unlink(missing_ok=True)
            raise

    def promote(self, staged: StagedBlob) -> str:
        key = self.storage_key(staged.content_hash)
        target = self.root / key
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            if target.exists():
                try:
                    self.verify(key, staged.content_hash, staged.byte_size)
                except (BlobIntegrityError, BlobNotFound):
                    os.replace(staged.path, target)
                else:
                    staged.path.unlink(missing_ok=True)
            else:
                os.replace(staged.path, target)
            directory_fd = None
            try:
                directory_fd = os.open(target.parent, os.O_RDONLY)
                os.fsync(directory_fd)
            except OSError:
                # Some platforms do not support fsync on directory handles.
                pass
            finally:
                if directory_fd is not None:
                    os.close(directory_fd)
            return key
        finally:
            staged.path.unlink(missing_ok=True)

    def verify(self, storage_key: str, expected_hash: str, expected_size: int) -> Path:
        if storage_key != self.storage_key(expected_hash):
            raise BlobIntegrityError("storage key does not match the recorded hash")
        path = self.root / storage_key
        if not path.is_file():
            raise BlobNotFound("stored file is missing")
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as stored_file:
            while chunk := stored_file.read(CHUNK_SIZE):
                digest.update(chunk)
                size += len(chunk)
        if size != expected_size or digest.hexdigest() != expected_hash:
            raise BlobIntegrityError("stored file failed its integrity check")
        return path
