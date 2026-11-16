"""Credential-free immutable preview sidecars for saved upload/check-in snapshots."""

import hashlib
import os
from pathlib import Path

MAX_BYTES = 1024 * 1024


def prepare(saved, preview):
    if not preview or preview.get("source_content_hash") != saved["content_hash"]:
        return None
    png = preview.get("png")
    if not isinstance(png, bytes) or not 0 < len(png) <= MAX_BYTES:
        return None
    path = Path(saved["directory"]) / "thumbnail.png"
    try:
        with path.open("xb") as stream:
            path.chmod(0o600)
            stream.write(png)
            stream.flush()
            os.fsync(stream.fileno())
        path.chmod(0o400)
    except OSError:
        return None
    return {
        "content_hash": hashlib.sha256(png).hexdigest(),
        "byte_size": len(png),
        "render_profile": "isometric-v1",
    }


def send(client, record, snapshot, metadata):
    if not metadata:
        return "Preview unavailable; the CAD snapshot was saved successfully."
    path = Path(snapshot).parent / "thumbnail.png"
    try:
        if metadata.get("render_profile") != "isometric-v1":
            raise ValueError("unsupported pending preview profile")
        if path.is_symlink() or path.stat().st_size > MAX_BYTES:
            raise ValueError("invalid preview sidecar")
        png = path.read_bytes()
        if (hashlib.sha256(png).hexdigest(), len(png)) != (
            metadata["content_hash"],
            metadata["byte_size"],
        ):
            raise ValueError("preview sidecar changed")
        for attempt in range(2):
            try:
                client.attach_thumbnail(record["id"], record["content_hash"], png)
                return None
            except Exception as error:
                if attempt or getattr(error, "code", "") != "connection_failed":
                    raise
    except Exception:
        return "Preview unavailable; the CAD snapshot was saved successfully. Retry Check In to recover a pending check-in preview."


def remove(snapshot):
    path = Path(snapshot).parent / "thumbnail.png"
    if path.is_file() and not path.is_symlink():
        path.chmod(0o600)
        path.unlink()
