"""Workspace isolation, exact reference graph and failure recovery regressions."""

import hashlib
import io
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from uuid import uuid4
from zipfile import ZipFile

import pytest

from freecad.forgepdm import fcstd, workspace
from freecad.forgepdm.api import ForgePDMError


def native(links=(), extra=""):
    objects = '<Object type="Part::Feature" name="Box"/>'
    data = '<Object name="Box"><Properties/></Object>'
    for name, filename, target in links:
        objects += '<Object type="App::Link" name="{}"/>'.format(name)
        data += '<Object name="{}"><Properties><Property name="LinkedObject" type="App::PropertyXLink"><XLink file="{}" name="{}"/></Property></Properties></Object>'.format(
            name, filename, target
        )
    content = "<Document><Objects>{}</Objects><ObjectData>{}</ObjectData>{}</Document>".format(
        objects, data, extra
    ).encode()
    result = io.BytesIO()
    with ZipFile(result, "w") as archive:
        archive.writestr("Document.xml", content)
        archive.writestr("Shape.brp", b"preserve geometry bytes")
    return result.getvalue()


class Client:
    base_url = "http://forgepdm.test"

    def __init__(self):
        self.revisions, self.datasets, self.manifests, self.files = {}, {}, {}, {}
        self.downloads = []
        self.uploads = []
        self.checkpoint = lambda: None
        self.fail_manifest = False

    def _checkpoint(self):
        self.checkpoint()

    def add(self, content, kind="part", references=()):
        revision_id, dataset_id, file_id, item_id = [str(uuid4()) for _ in range(4)]
        self.revisions[revision_id] = {
            "id": revision_id,
            "item_id": item_id,
            "item_number": "P000001",
            "label": "A",
            "item_kind": kind,
        }
        record = {
            "id": file_id,
            "content_hash": hashlib.sha256(content).hexdigest(),
            "byte_size": len(content),
        }
        self.files[file_id] = content
        self.datasets[revision_id] = [
            {"id": dataset_id, "dataset_type": "native_cad", "files": [record]}
        ]
        self.manifests[dataset_id] = {
            "source_file_id": file_id,
            "profile": workspace.PROFILE,
            "references": list(references),
        }
        return revision_id, dataset_id, file_id

    def get_revision(self, revision_id):
        return self.revisions[revision_id]

    def list_datasets(self, revision_id):
        return self.datasets[revision_id]

    def get_bom(self, revision_id):
        return []

    def get_manifest(self, dataset_id):
        if self.fail_manifest:
            raise ForgePDMError("dependency unavailable", 403)
        return self.manifests[dataset_id]

    def download_file(self, file_id, destination, expected_hash=None, expected_size=None):
        content = self.files[file_id]
        assert (
            hashlib.sha256(content).hexdigest() == expected_hash and len(content) == expected_size
        )
        Path(destination).write_bytes(content)
        self.downloads.append(file_id)

    def upload_file(self, revision_id, path, *args):
        content = Path(path).read_bytes()
        self.uploads.append(content)
        dataset_id, file_id = str(uuid4()), str(uuid4())
        return {
            "id": dataset_id,
            "files": [
                {
                    "id": file_id,
                    "content_hash": hashlib.sha256(content).hexdigest(),
                    "byte_size": len(content),
                }
            ],
        }

    def attach_manifest(self, dataset_id, file_id, references):
        self.manifests[dataset_id] = {
            "source_file_id": file_id,
            "references": references,
            "profile": workspace.PROFILE,
        }


def reference(target, name="Link"):
    return {
        "object_name": name,
        "property_name": "LinkedObject",
        "target_object_name": "Box",
        "target_revision_id": target[0],
        "target_dataset_id": target[1],
        "target_file_id": target[2],
    }


def test_nested_graph_is_pinned_verified_and_rewritten_before_open(tmp_path):
    client = Client()
    child = client.add(native())
    sub = client.add(
        native([("Link", "/old/component.FCStd", "Box")]), "assembly", [reference(child)]
    )
    root = client.add(
        native(
            [("Link", "/old/subassembly.FCStd", "Box"), ("Second", "/old/subassembly.FCStd", "Box")]
        ),
        "assembly",
        [reference(sub), reference(sub, "Second")],
    )
    result = workspace.retrieve(client, tmp_path, *root)
    directory = Path(result["directory"])
    assert result["ledger"]["state"] == "prepared"
    assert len(result["ledger"]["documents"]) == 3
    assert client.downloads == [root[2], sub[2], child[2]]
    _tree, links = fcstd.inspect(directory / ("documents/" + root[2] + ".FCStd"))
    for link in links:
        assert not Path(link["file"]).is_absolute()
        assert (directory / "documents" / link["file"]).resolve() == directory / "documents" / (
            sub[2] + ".FCStd"
        )
    workspace.finish(client, result)
    assert json.loads((directory / workspace.MANIFEST).read_text())["state"] == "complete"
    assert (directory / "documents" / (root[2] + ".FCStd")).stat().st_mode & 0o222 == 0


def test_repeated_retrieval_never_overwrites_existing_local_configuration(tmp_path):
    client = Client()
    root = client.add(native())
    first = workspace.retrieve(client, tmp_path, *root)
    file = Path(first["directory"]) / first["ledger"]["documents"][0]["path"]
    file.write_bytes(b"unsaved user content on disk")
    second = workspace.retrieve(client, tmp_path, *root)
    assert first["directory"] != second["directory"]
    assert file.read_bytes() == b"unsaved user content on disk"
    assert len(client.downloads) == 1


def test_cache_corruption_fails_without_replacing_data(tmp_path):
    client = Client()
    root = client.add(native())
    first = workspace.retrieve(client, tmp_path, *root)
    cache = tmp_path / ".forgepdm/cache" / first["ledger"]["documents"][0]["content_hash"]
    cache.chmod(0o600)
    cache.write_bytes(b"corrupt")
    with pytest.raises(workspace.WorkspaceError, match="integrity"):
        workspace.retrieve(client, tmp_path, *root)
    assert cache.read_bytes() == b"corrupt"
    assert len(list((tmp_path / "configurations").iterdir())) == 1
    assert not list((tmp_path / ".forgepdm/staging").iterdir())


def test_denied_dependency_leaves_no_published_configuration(tmp_path):
    client = Client()
    root = client.add(native())
    client.fail_manifest = True
    with pytest.raises(ForgePDMError):
        workspace.retrieve(client, tmp_path, *root)
    assert not (tmp_path / "configurations").exists()
    assert not list((tmp_path / ".forgepdm/staging").iterdir())


def test_missing_manifest_is_allowed_only_for_self_contained_legacy_files(tmp_path):
    client = Client()
    root = client.add(native())
    client.manifests[root[1]] = None
    assert workspace.retrieve(client, tmp_path, *root)
    assembly = client.add(native([("Link", "/old/part.FCStd", "Box")]), "assembly")
    client.manifests[assembly[1]] = None
    with pytest.raises(workspace.WorkspaceError, match="legacy assembly"):
        workspace.retrieve(client, tmp_path, *assembly)


def test_bom_revision_mismatch_stops_retrieval_before_open(tmp_path):
    client = Client()
    child = client.add(native())
    root = client.add(native([("Link", "old.FCStd", "Box")]), "assembly", [reference(child)])
    client.get_bom = lambda revision_id: [{"component_revision_id": str(uuid4())}]
    with pytest.raises(workspace.WorkspaceError, match="BOM"):
        workspace.retrieve(client, tmp_path, *root)
    assert not (tmp_path / "configurations").exists()


def test_configuration_remains_relocatable(tmp_path):
    client = Client()
    child = client.add(native())
    root = client.add(
        native([("Link", "/source/child.FCStd", "Box")]), "assembly", [reference(child)]
    )
    configuration = workspace.retrieve(client, tmp_path / "first", *root)
    workspace.finish(client, configuration)
    shutil.copytree(tmp_path / "first", tmp_path / "relocated")
    original = Path(configuration["directory"])
    moved = tmp_path / "relocated/configurations" / original.name
    root_file = moved / "documents" / (root[2] + ".FCStd")
    entry = workspace.binding(root_file, client.base_url)
    assert entry["root"] == tmp_path / "relocated"
    _tree, links = fcstd.inspect(root_file)
    assert (root_file.parent / links[0]["file"]).resolve().is_relative_to(moved)


def test_dirty_linked_component_is_not_silently_rebound(tmp_path):
    client = Client()
    path = Path(workspace.prepare_working(client.base_url, tmp_path))
    path.write_bytes(native())
    item_id, revision_id = str(uuid4()), str(uuid4())
    workspace.upload(client, str(path), revision_id, item_id, [])
    path.write_bytes(native(extra="<Changed/>"))
    ref = {
        "object_name": "Link",
        "target_path": str(path),
        "target_object_name": "Box",
        "target_item_id": item_id,
        "target_revision_id": revision_id,
    }
    with pytest.raises(workspace.WorkspaceError, match="unuploaded"):
        workspace.bind_references(client, [ref])


def test_snapshot_upload_does_not_read_later_working_file_edits(tmp_path):
    client = Client()
    path = Path(workspace.prepare_working(client.base_url, tmp_path))
    initial = native()
    path.write_bytes(initial)
    upload = client.upload_file

    def change(revision, path_to_snapshot, *args):
        path.write_bytes(b"later edits")
        return upload(revision, path_to_snapshot, *args)

    client.upload_file = change
    result = workspace.upload(client, str(path), str(uuid4()), str(uuid4()), [])
    assert client.uploads == [initial]
    assert result["local_changes_remain"]
    assert not list((tmp_path / ".forgepdm/uploads").iterdir())
    assert path.read_bytes() == b"later edits"


def test_another_process_cannot_claim_workspace_lock(tmp_path, addon_root):
    script = """import sys
sys.path.insert(0,sys.argv[1])
from freecad.forgepdm.workspace import locked, WorkspaceError
try:
    with locked(sys.argv[2],"http://forgepdm.test"): pass
except WorkspaceError:
    print("blocked")
else:
    raise AssertionError("second owner acquired lock")
"""
    with workspace.locked(tmp_path, "http://forgepdm.test"):
        result = subprocess.run(
            [sys.executable, "-I", "-S", "-c", script, str(addon_root), str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "blocked"


def test_dead_owner_recovery_preserves_old_lock_evidence(tmp_path):
    if sys.platform == "win32":
        pytest.skip("POSIX dead-owner recovery only")
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    admin = tmp_path / ".forgepdm"
    admin.mkdir()
    (admin / "lock.json").write_text(
        json.dumps({"pid": child.pid, "host": socket.gethostname(), "token": "old"})
    )
    with workspace.locked(tmp_path, "http://forgepdm.test"):
        pass
    assert list(admin.glob("recovered-lock-*.json"))
    assert not (admin / "lock.json").exists()


def test_workspace_server_identity_and_symlink_boundaries(tmp_path):
    with workspace.locked(tmp_path, "http://one.test"):
        pass
    with pytest.raises(workspace.WorkspaceError, match="another"):
        with workspace.locked(tmp_path, "http://two.test"):
            pass
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    lock = tmp_path / ".forgepdm/lock.json"
    lock.symlink_to(outside)
    with pytest.raises(workspace.WorkspaceError, match="symlink"):
        with workspace.locked(tmp_path, "http://one.test"):
            pass
    assert outside.read_text() == "{}"


@pytest.mark.parametrize(
    "content", [b"not a ZIP", native(extra='<Expression expression="Other#Box.Length"/>')]
)
def test_unsupported_native_content_is_rejected(tmp_path, content):
    path = tmp_path / "invalid.FCStd"
    path.write_bytes(content)
    with pytest.raises(fcstd.CADIntegrityError):
        fcstd.inspect(path)


def test_native_manifest_mismatch_is_not_ignored(tmp_path):
    path = tmp_path / "assembly.FCStd"
    path.write_bytes(native([("Link", "/old.FCStd", "Box")]))
    with pytest.raises(fcstd.CADIntegrityError, match="manifest"):
        fcstd.validate(path, [])


def test_changing_file_is_detected_during_hashing(tmp_path):
    path = tmp_path / "file"
    path.write_bytes(b"x" * (2 * 1024 * 1024))
    changed = []

    def change():
        if not changed:
            with path.open("r+b") as file:
                file.seek(-1, 2)
                file.write(b"y")
            changed.append(True)

    with pytest.raises(workspace.WorkspaceError, match="changed"):
        workspace.digest(path, change)


def test_failed_finalization_does_not_mark_configuration_complete(tmp_path, monkeypatch):
    client = Client()
    root = client.add(native())
    result = workspace.retrieve(client, tmp_path, *root)
    original = Path.chmod

    def fail(path, mode, *args, **kwargs):
        if path.suffix == ".FCStd":
            raise PermissionError("Injected protection failure")
        return original(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "chmod", fail)
    with pytest.raises(PermissionError):
        workspace.finish(client, result)
    ledger = json.loads((Path(result["directory"]) / workspace.MANIFEST).read_text())
    assert ledger["state"] == "prepared"


def test_recovery_guard_prevents_competing_dead_lock_recovery(tmp_path):
    client = Client()
    workspace.prepare_working(client.base_url, tmp_path)
    admin = tmp_path / ".forgepdm"
    (admin / "lock.json").write_text(json.dumps({"pid": 999999999, "host": socket.gethostname()}))
    (admin / "lock-recovery").mkdir()
    with pytest.raises(workspace.WorkspaceError, match="recovery"):
        workspace.prepare_working(client.base_url, tmp_path)
    assert (admin / "lock.json").exists()


def test_archive_rewrite_honors_cancellation_without_changing_source(tmp_path):
    client = Client()
    root = client.add(native())
    def cancelled():
        raise RuntimeError("cancelled during archive rewrite")
    source = tmp_path / "source.FCStd"
    source.write_bytes(client.files[root[2]])
    with pytest.raises(RuntimeError, match="cancelled"):
        fcstd.rewrite(source, tmp_path / "output.FCStd", [], {}, cancelled)
    assert source.read_bytes() == client.files[root[2]]


def test_native_zip_member_traversal_is_rejected(tmp_path):
    source = tmp_path / "unsafe.FCStd"
    source.write_bytes(native())
    with ZipFile(source, "a") as archive:
        archive.writestr("../outside", b"unsafe")
    with pytest.raises(fcstd.CADIntegrityError, match="unsafe member"):
        fcstd.inspect(source)
