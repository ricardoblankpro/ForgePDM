"""Local workspace ledger, verified cache and isolated configurations.

All authoritative identities come through the HTTP API. This module never reads
the server's database or blob directory and has no FreeCAD dependency.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import tempfile
from uuid import UUID, uuid4

from .fcstd import inspect, rewrite, validate


MANIFEST = "forgepdm-workspace.json"
PROFILE = "freecad-app-link-v1"


class WorkspaceError(Exception):
    """Workspace is dirty, belongs to another server, or is incomplete."""


def _id(value):
    return str(UUID(value))


def _atomic_json(path, data):
    descriptor, temporary = tempfile.mkstemp(prefix=".ledger-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as output:
            json.dump(data, output, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def digest(path, checkpoint=lambda: None):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise WorkspaceError("Missing or linked workspace file: " + str(path))
    before = path.stat()
    value, size = hashlib.sha256(), 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            checkpoint()
            value.update(chunk)
            size += len(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (
        after.st_size,
        after.st_mtime_ns,
        after.st_ino,
    ):
        raise WorkspaceError("The local CAD file changed during integrity verification")
    return value.hexdigest(), size


def _safe_path(root, relative):
    root = Path(root)
    path = root / relative
    if not relative or "\\" in relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise WorkspaceError("Invalid path in workspace ledger")
    if path.resolve() != path.absolute() or not path.resolve().is_relative_to(root.resolve()):
        raise WorkspaceError(
            "Workspace file paths must not traverse links or escape their configuration"
        )
    return path


@contextmanager
def locked(root, server):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    admin = root / ".forgepdm"
    if admin.is_symlink():
        raise WorkspaceError("Workspace metadata directory must not be a symlink")
    admin.mkdir(exist_ok=True)
    lock = admin / "lock.json"
    if lock.is_symlink():
        raise WorkspaceError("Workspace lock must not be a symlink")
    token = uuid4().hex
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        # Recover only a provably dead owner on the same local POSIX host.
        # Never use os.kill(pid, 0) on Windows, where its semantics differ.
        # Serialize recovery attempts so a second recoverer cannot move the
        # first recoverer's new live lock. A crashed recovery guard fails closed.
        recovery = admin / "lock-recovery"
        try:
            recovery.mkdir()
        except FileExistsError as error:
            raise WorkspaceError("Workspace lock recovery is in progress or needs inspection") from error
        try:
            try:
                previous = json.loads(lock.read_text())
                if os.name != "posix" or previous["host"] != socket.gethostname():
                    raise WorkspaceError("Workspace is locked; close the other client before retrying")
                try:
                    os.kill(int(previous["pid"]), 0)
                except ProcessLookupError:
                    lock.rename(admin / ("recovered-lock-" + uuid4().hex + ".json"))
                else:
                    raise WorkspaceError("Another ForgePDM operation is using this workspace")
            except (ValueError, KeyError, OSError) as error:
                raise WorkspaceError("Workspace lock requires manual inspection") from error
        finally:
            recovery.rmdir()
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "w") as output:
            json.dump({"pid": os.getpid(), "host": socket.gethostname(), "token": token}, output)
        identity = admin / "identity.json"
        if identity.exists():
            if (
                identity.is_symlink()
                or json.loads(identity.read_text()).get("server_url") != server
            ):
                raise WorkspaceError("This workspace belongs to another ForgePDM server")
        else:
            _atomic_json(identity, {"format": 1, "server_url": server})
        for name in ("cache", "staging", "uploads"):
            path = admin / name
            if path.is_symlink():
                raise WorkspaceError("Workspace directories must not be symlinks")
            path.mkdir(exist_ok=True)
        yield root
    finally:
        if lock.exists() and not lock.is_symlink():
            try:
                if json.loads(lock.read_text()).get("token") == token:
                    lock.unlink()
            except (ValueError, OSError):
                # Leave an unreadable/changed lock for inspection; never remove
                # another process's ownership record.
                pass


def prepare_working(server, root):
    with locked(root, server) as root:
        parent = root / "working"
        if parent.is_symlink():
            raise WorkspaceError("Workspace working directory must not be a symlink")
        parent.mkdir(exist_ok=True)
        directory = parent / uuid4().hex
        directory.mkdir()
        ledger = {
            "format": 1,
            "id": directory.name,
            "server_url": server,
            "state": "working",
            "documents": [{"path": "model.FCStd"}],
        }
        _atomic_json(directory / MANIFEST, ledger)
        return str(directory / "model.FCStd")


def binding(path, server=None, require_uploaded=True):
    path = Path(path).absolute()
    for directory in path.parents:
        ledger_path = directory / MANIFEST
        if not ledger_path.exists():
            continue
        if ledger_path.is_symlink():
            raise WorkspaceError("Workspace ledger must not be a symlink")
        ledger = json.loads(ledger_path.read_text())
        if ledger.get("format") != 1 or ledger.get("id") != directory.name:
            raise WorkspaceError("Invalid workspace ledger identity")
        if directory.parent.name not in ("working", "configurations"):
            raise WorkspaceError("Unrecognized workspace configuration directory")
        root = directory.parent.parent
        identity = json.loads((root / ".forgepdm/identity.json").read_text())
        if identity.get("server_url") != ledger.get("server_url") or (
            server is not None and server != ledger.get("server_url")
        ):
            raise WorkspaceError("The CAD document belongs to a different ForgePDM server")
        for entry in ledger["documents"]:
            if _safe_path(directory, entry["path"]) == path:
                if require_uploaded and not all(
                    entry.get(key)
                    for key in ("item_id", "revision_id", "dataset_id", "file_id", "working_hash")
                ):
                    raise WorkspaceError(
                        "Upload the component from this workspace before using it in an assembly"
                    )
                return {"root": root, "directory": directory, "ledger": ledger, "entry": entry}
        raise WorkspaceError("The document is not registered in its workspace ledger")
    raise WorkspaceError(
        "This document has no managed workspace. Upload or retrieve it with ForgePDM first."
    )


def working_path(path, server):
    try:
        value = binding(path, server, require_uploaded=False)
    except WorkspaceError:
        # A foreign/invalid ledger is a conflict, not permission to silently
        # adopt it as an unmanaged file.
        if any((directory / MANIFEST).exists() for directory in Path(path).absolute().parents):
            raise
        return None
    if value["directory"].parent.name != "working":
        return None
    return value


def bind_references(client, references):
    result = []
    for reference in references:
        client._checkpoint()
        value = binding(reference["target_path"], client.base_url)
        entry = value["entry"]
        current, _size = digest(reference["target_path"], client._checkpoint)
        if current != entry["working_hash"]:
            raise WorkspaceError(
                "A linked component has unuploaded local changes. Upload that component first."
            )
        if (
            entry["item_id"] != reference["target_item_id"]
            or entry["revision_id"] != reference["target_revision_id"]
        ):
            raise WorkspaceError("Linked component metadata differs from its recorded revision")
        result.append(
            {
                "object_name": reference["object_name"],
                "property_name": "LinkedObject",
                "target_object_name": reference["target_object_name"],
                "target_revision_id": entry["revision_id"],
                "target_dataset_id": entry["dataset_id"],
                "target_file_id": entry["file_id"],
                "target_path": reference["target_path"],
            }
        )
    return result


def snapshot(client, path, references):
    value = binding(path, client.base_url, require_uploaded=False)
    directory = value["root"] / ".forgepdm/uploads" / uuid4().hex
    directory.mkdir()
    destination = directory / "model.FCStd"
    try:
        expected, size = digest(path, client._checkpoint)
        validate(path, references, source_path=path)
        with open(path, "rb") as source, destination.open("xb") as target:
            while chunk := source.read(1024 * 1024):
                client._checkpoint()
                target.write(chunk)
        if digest(destination, client._checkpoint) != (expected, size) or digest(
            path, client._checkpoint
        ) != (expected, size):
            raise WorkspaceError("The working file changed while taking the upload snapshot")
        destination.chmod(0o444)
        return {
            "directory": str(directory),
            "path": str(destination),
            "content_hash": expected,
            "byte_size": size,
        }
    except BaseException:
        shutil.rmtree(directory)
        raise


def upload(client, path, revision_id, item_id, references):
    """Upload one stable snapshot and bind its immutable dependency manifest."""
    references = bind_references(client, references)
    saved = snapshot(client, path, references)
    try:
        dataset = client.upload_file(revision_id, saved["path"], "native_cad", "Native CAD")
        record = dataset["files"][0]
        if (
            record["content_hash"] != saved["content_hash"]
            or record["byte_size"] != saved["byte_size"]
        ):
            raise WorkspaceError("Uploaded bytes differ from the prepared snapshot")
        serialized = [
            {key: value for key, value in reference.items() if key != "target_path"}
            for reference in references
        ]
        client.attach_manifest(dataset["id"], record["id"], serialized)
        value = binding(path, client.base_url, require_uploaded=False)
        with locked(value["root"], client.base_url):
            ledger = json.loads((value["directory"] / MANIFEST).read_text())
            entry = next(
                entry for entry in ledger["documents"] if entry["path"] == value["entry"]["path"]
            )
            entry.update(
                {
                    "item_id": item_id,
                    "revision_id": revision_id,
                    "dataset_id": dataset["id"],
                    "file_id": record["id"],
                    "content_hash": record["content_hash"],
                    "byte_size": record["byte_size"],
                    "working_hash": saved["content_hash"],
                    "references": serialized,
                }
            )
            ledger["state"] = "working"
            _atomic_json(value["directory"] / MANIFEST, ledger)
        dataset["local_changes_remain"] = (
            digest(path, client._checkpoint)[0] != saved["content_hash"]
        )
        return dataset
    finally:
        Path(saved["path"]).chmod(0o600)
        shutil.rmtree(saved["directory"])


def retrieve(client, root, revision_id, dataset_id, file_id):
    """Download/verify a pinned DAG, patch owned copies, publish as incomplete."""
    with locked(root, client.base_url) as root:
        directory = root / ".forgepdm/staging" / uuid4().hex
        directory.mkdir()
        nodes, order, active = {}, [], set()
        try:

            def visit(revision_id, dataset_id, file_id):
                client._checkpoint()
                key = (_id(revision_id), _id(dataset_id), _id(file_id))
                if key in active:
                    raise WorkspaceError("CAD dependency graph contains a cycle")
                if file_id in nodes:
                    if (
                        nodes[file_id]["revision_id"] != revision_id
                        or nodes[file_id]["dataset_id"] != dataset_id
                    ):
                        raise WorkspaceError(
                            "CAD file identity is inconsistent across dependencies"
                        )
                    return
                if len(nodes) >= 1000 or len(active) >= 100:
                    raise WorkspaceError("CAD dependency graph exceeds the supported size/depth")
                active.add(key)
                revision = client.get_revision(revision_id)
                datasets = client.list_datasets(revision_id)
                dataset = next(
                    (
                        value
                        for value in datasets
                        if value["id"] == dataset_id and value["dataset_type"] == "native_cad"
                    ),
                    None,
                )
                record = (
                    next((value for value in dataset["files"] if value["id"] == file_id), None)
                    if dataset
                    else None
                )
                if record is None:
                    raise WorkspaceError("The pinned native dataset/file is no longer available")
                content_hash = record["content_hash"]
                if len(content_hash) != 64 or any(
                    character not in "0123456789abcdef" for character in content_hash
                ):
                    raise WorkspaceError("Server returned an invalid content hash")
                cached = root / ".forgepdm/cache" / content_hash
                if cached.exists():
                    if digest(cached, client._checkpoint) != (content_hash, record["byte_size"]):
                        raise WorkspaceError(
                            "Cached CAD bytes failed integrity verification. Preserve the workspace and inspect its cache."
                        )
                else:
                    client.download_file(
                        file_id,
                        str(cached),
                        expected_hash=content_hash,
                        expected_size=record["byte_size"],
                    )
                    cached.chmod(0o444)
                manifest = client.get_manifest(dataset_id)
                if manifest is None:
                    _tree, external = inspect(cached)
                    if external:
                        raise WorkspaceError(
                            "This legacy assembly has no recorded CAD dependencies. Re-upload its components and assembly using the managed workspace."
                        )
                    references = []
                else:
                    if manifest["source_file_id"] != file_id or manifest["profile"] != PROFILE:
                        raise WorkspaceError(
                            "CAD manifest identifies a different source file or unsupported profile"
                        )
                    references = manifest["references"]
                validate(cached, references)
                node = {
                    "item_id": revision["item_id"],
                    "item_number": revision["item_number"],
                    "revision_id": revision_id,
                    "revision_label": revision["label"],
                    "dataset_id": dataset_id,
                    "file_id": file_id,
                    "content_hash": content_hash,
                    "byte_size": record["byte_size"],
                    "path": "documents/" + file_id + ".FCStd",
                    "references": references,
                }
                if revision["item_kind"] == "assembly":
                    bom = client.get_bom(revision_id)
                    if bom and {line["component_revision_id"] for line in bom} != {
                        reference["target_revision_id"] for reference in references
                    }:
                        raise WorkspaceError(
                            "Stored BOM component revisions differ from the CAD reference manifest. Retrieval stopped before opening files."
                        )
                    node["bom_revision_check"] = "matched" if bom else "not_synchronized"
                nodes[file_id] = node
                for reference in references:
                    target_key = (
                        reference["target_revision_id"],
                        reference["target_dataset_id"],
                        reference["target_file_id"],
                    )
                    if target_key in active:
                        raise WorkspaceError("CAD dependency graph contains a cycle")
                    visit(*target_key)
                active.remove(key)
                order.append(file_id)

            visit(revision_id, dataset_id, file_id)
            documents = directory / "documents"
            documents.mkdir()
            targets = {key: _safe_path(directory, node["path"]) for key, node in nodes.items()}
            for key in order:
                node = nodes[key]
                rewrite(
                    root / ".forgepdm/cache" / node["content_hash"],
                    targets[key],
                    node["references"],
                    targets,
                    client._checkpoint,
                )
            ledger = {
                "format": 1,
                "id": directory.name,
                "server_url": client.base_url,
                "state": "prepared",
                "root_file_id": file_id,
                "order": order,
                "documents": list(nodes.values()),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            _atomic_json(directory / MANIFEST, ledger)
            final_parent = root / "configurations"
            if final_parent.is_symlink():
                raise WorkspaceError("Workspace configuration directory must not be a symlink")
            final_parent.mkdir(exist_ok=True)
            final = final_parent / directory.name
            directory.rename(final)
            return {"directory": str(final), "ledger": ledger}
        finally:
            if directory.exists():
                shutil.rmtree(directory)


def finish(client, configuration):
    directory = Path(configuration["directory"])
    ledger_path = directory / MANIFEST
    if ledger_path.is_symlink() or directory.parent.name != "configurations":
        raise WorkspaceError("Invalid retrieved configuration path")
    ledger = json.loads(ledger_path.read_text())
    if ledger.get("id") != directory.name or ledger.get("server_url") != client.base_url:
        raise WorkspaceError("Retrieved configuration identity changed")
    with locked(directory.parent.parent, client.base_url):
        for entry in ledger["documents"]:
            path = _safe_path(directory, entry["path"])
            entry["working_hash"] = digest(path, client._checkpoint)[0]
            path.chmod(0o444)
        ledger["state"] = "complete"
        _atomic_json(directory / MANIFEST, ledger)
    return ledger


def incomplete(configuration):
    directory = Path(configuration["directory"])
    ledger = json.loads((directory / MANIFEST).read_text())
    if ledger["state"] != "complete":
        ledger["state"] = "incomplete"
        _atomic_json(directory / MANIFEST, ledger)
