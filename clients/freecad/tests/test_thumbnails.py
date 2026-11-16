"""Preview source fencing and durable sidecars never replace CAD intent."""

import hashlib
import json
import sys
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_part_checkin import case, journal, native

from freecad.forgepdm import part_checkin, thumbnail_transfer, workspace
from freecad.forgepdm.api import ForgePDMClient, ForgePDMError


def preview(path):
    return {"source_content_hash": workspace.digest(path)[0], "png": b"immutable preview bytes"}


def test_checkin_recovers_preview_after_lost_cad_and_image_responses(tmp_path):
    client, path, args = case(tmp_path)
    original = preview(path)
    sent, stored = [], {}
    lost = [True]

    def attach(file_id, source_hash, png):
        sent.append((file_id, source_hash, png))
        stored[file_id] = (source_hash, png)
        if lost[0]:
            lost[0] = False
            raise ForgePDMError("lost preview response", code="connection_failed")

    client.attach_thumbnail = attach
    client.lose_response = True
    try:
        part_checkin.checkin(*args, preview=original)
    except ForgePDMError:
        pass
    else:
        raise AssertionError("expected lost CAD response")
    assert journal(path)["thumbnail"]["content_hash"] == hashlib.sha256(original["png"]).hexdigest()
    path.write_bytes(native("<NewerUnsavedWork/>"))
    result = part_checkin.resume(*args)
    assert result["local_changes_remain"] and not result["thumbnail_warning"]
    assert len(client.sent) == 1 and len(sent) == 2
    assert sent[0] == sent[1] and sent[0][2] == original["png"]
    assert journal(path)["thumbnail_state"] == "completed"
    assert len(stored) == 1


def test_preview_failure_leaves_checkin_successful_and_retryable(tmp_path):
    client, path, args = case(tmp_path)
    client.attach_thumbnail = lambda *args: (_ for _ in ()).throw(
        ForgePDMError("offline", code="connection_failed")
    )
    result = part_checkin.checkin(*args, preview=preview(path))
    assert result["status"] == "completed" and result["thumbnail_warning"]
    operation = journal(path)
    snapshot = tmp_path / operation["snapshot_path"]
    assert (snapshot.parent / "thumbnail.png").is_file()
    sent = []
    client.attach_thumbnail = lambda *args: sent.append(args)
    recovered = part_checkin.resume(*args)
    assert not recovered["thumbnail_warning"]
    assert len(sent) == 1 and len(client.sent) == 1
    assert not (snapshot.parent / "thumbnail.png").exists()


def test_changed_snapshot_never_receives_newer_preview(tmp_path):
    client, path, args = case(tmp_path)
    wrong = preview(path)
    path.write_bytes(native("<DifferentSavedBytes/>"))
    sent = []
    client.attach_thumbnail = lambda *args: sent.append(args)
    result = part_checkin.checkin(*args, preview=wrong)
    assert result["status"] == "completed" and not sent
    assert result["thumbnail_warning"]


def test_changed_preview_sidecar_is_preserved_without_upload(tmp_path):
    client, path, args = case(tmp_path)
    client.attach_thumbnail = lambda *args: (_ for _ in ()).throw(ForgePDMError("offline"))
    part_checkin.checkin(*args, preview=preview(path))
    operation = journal(path)
    image = tmp_path / Path(operation["snapshot_path"]).parent / "thumbnail.png"
    image.chmod(0o600)
    image.write_bytes(b"newer wrong image")
    calls = []
    client.attach_thumbnail = lambda *args: calls.append(args)
    assert part_checkin.resume(*args)["thumbnail_warning"]
    assert not calls and image.exists()


def test_upload_adds_preview_only_after_exact_file_and_manifest_are_confirmed(tmp_path):

    # Transfer helper itself never invents identity from the current live document.
    saved = {"directory": str(tmp_path), "content_hash": "a" * 64}
    payload = {"source_content_hash": "b" * 64, "png": b"wrong"}
    assert thumbnail_transfer.prepare(saved, payload) is None
    assert not (tmp_path / "thumbnail.png").exists()
    payload["source_content_hash"] = "a" * 64
    metadata = thumbnail_transfer.prepare(saved, payload)
    assert metadata["byte_size"] == 5
    assert "token" not in json.dumps(metadata)


def test_preview_client_rejects_wrong_source_response_and_bounds_transfer(monkeypatch):
    client = ForgePDMClient("http://thumbnail.test")
    result = {
        "source_file_id": "file",
        "source_content_hash": "a" * 64,
        "render_profile": "isometric-v1",
        "content_hash": "b" * 64,
        "width": 384,
        "height": 384,
        "byte_size": 42,
    }
    options = []
    monkeypatch.setattr(
        client, "_json_request", lambda *args, **kwargs: options.append(kwargs) or result
    )
    assert client.attach_thumbnail("file", "a" * 64, b"png") == result
    assert options[0]["timeout"] == 10
    result["source_file_id"] = "another-file"
    with pytest.raises(ForgePDMError, match="different snapshot"):
        client.attach_thumbnail("file", "a" * 64, b"png")


def test_preview_download_rejects_hash_source_and_dimension_mismatch(monkeypatch):
    client = ForgePDMClient("http://thumbnail.test")
    client.token = "memory-only-test-token"
    raw = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + (384).to_bytes(4, "big") * 2
    headers = {
        "Content-Type": "image/png",
        "X-ForgePDM-Source-Hash": "a" * 64,
        "X-Content-SHA256": hashlib.sha256(raw).hexdigest(),
    }

    def response(*args, **kwargs):
        stream = BytesIO(raw)
        stream.headers = headers
        return stream

    monkeypatch.setattr("urllib.request.urlopen", response)
    assert client.get_thumbnail("file", "a" * 64) == raw
    with pytest.raises(ForgePDMError):
        client.get_thumbnail("file", "b" * 64)
    headers["X-Content-SHA256"] = "c" * 64
    with pytest.raises(ForgePDMError):
        client.get_thumbnail("file", "a" * 64)


def test_unsaved_recomputed_linked_component_blocks_capture_without_touching_files(
    tmp_path, monkeypatch
):
    from freecad.forgepdm import thumbnail_render

    source, child_path = tmp_path / "parent.FCStd", tmp_path / "child.FCStd"
    source.write_bytes(b"saved parent")
    child_path.write_bytes(b"saved child")
    parent = SimpleNamespace(Name="parent", FileName=str(source), isTouched=lambda: False)
    child = SimpleNamespace(Name="child", FileName=str(child_path), isTouched=lambda: False)
    monkeypatch.setitem(
        sys.modules,
        "FreeCAD",
        SimpleNamespace(listDocuments=lambda: {"parent": parent, "child": child}),
    )
    monkeypatch.setitem(
        sys.modules,
        "FreeCADGui",
        SimpleNamespace(getDocument=lambda name: SimpleNamespace(Modified=name == "child")),
    )
    monkeypatch.setattr(
        thumbnail_render.cad,
        "capture",
        lambda doc: [{"target_path": str(child_path)}] if doc is parent else [],
    )
    with pytest.raises(ValueError, match="unsaved"):
        thumbnail_render.capture(parent)
    assert source.read_bytes() == b"saved parent" and child_path.read_bytes() == b"saved child"


def test_render_exception_restores_native_camera_type_animation_selection_and_file(
    tmp_path, monkeypatch
):
    from freecad.forgepdm import thumbnail_render

    source = tmp_path / "model.FCStd"
    source.write_bytes(b"unchanged saved CAD")
    document = SimpleNamespace(Name="model", FileName=str(source), isTouched=lambda: False)

    class View:
        camera_type, animation = "Perspective", True
        fields = {"rotation": "original", "zoom": 123}

        def getCameraType(self):
            return self.camera_type

        def getCamera(self):
            return repr(self.fields)

        def getCameraNode(self):
            return SimpleNamespace(
                copy=lambda: dict(self.fields),
                copyFieldValues=lambda state: setattr(self, "fields", state),
            )

        def isAnimationEnabled(self):
            return self.animation

        def setAnimationEnabled(self, value):
            self.animation = value

        def setCameraType(self, value):
            self.camera_type = value

        def viewIsometric(self):
            self.fields = {"rotation": "isometric", "zoom": 1}

        def fitAll(self):
            self.fields["zoom"] = 5

        def saveImage(self, *args):
            raise RuntimeError("injected renderer failure")

    view, selected = View(), []
    selection = SimpleNamespace(
        getSelectionEx=lambda: [
            SimpleNamespace(DocumentName="model", ObjectName="Box", SubElementNames=("Face1",))
        ],
        clearSelection=selected.clear,
        addSelection=lambda *args: selected.append(args),
    )
    monkeypatch.setitem(
        sys.modules, "FreeCAD", SimpleNamespace(listDocuments=lambda: {"model": document})
    )
    monkeypatch.setitem(
        sys.modules,
        "FreeCADGui",
        SimpleNamespace(
            getDocument=lambda name: SimpleNamespace(Modified=False, activeView=lambda: view),
            Selection=selection,
        ),
    )
    monkeypatch.setattr(thumbnail_render.cad, "capture", lambda doc: [])
    with pytest.raises(RuntimeError, match="renderer failure"):
        thumbnail_render.capture(document)
    assert view.camera_type == "Perspective" and view.animation
    assert view.fields == {"rotation": "original", "zoom": 123}
    assert selected == [("model", "Box", "Face1")]
    assert source.read_bytes() == b"unchanged saved CAD"
