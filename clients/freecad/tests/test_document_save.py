"""Regression coverage for upload from read-only FreeCAD example documents."""

import importlib
import sys
from types import ModuleType, SimpleNamespace

import pytest


@pytest.fixture
def commands(addon_root, monkeypatch):
    monkeypatch.syspath_prepend(str(addon_root))
    before = set(sys.modules)
    app = ModuleType("FreeCAD")
    app.ActiveDocument = None
    gui = ModuleType("FreeCADGui")
    gui.getMainWindow = lambda: None
    qt = ModuleType("PySide")
    qt.QtCore = SimpleNamespace()
    qt.QtGui = SimpleNamespace()
    qt.QtWidgets = SimpleNamespace(QFileDialog=SimpleNamespace())
    for name, module in (("FreeCAD", app), ("FreeCADGui", gui), ("PySide", qt)):
        monkeypatch.setitem(sys.modules, name, module)
    module = importlib.import_module("freecad.forgepdm.commands")
    yield module
    for name in set(sys.modules) - before:
        if name == "freecad" or name.startswith("freecad."):
            del sys.modules[name]


class Document:
    Label = "Example"

    def __init__(self, path):
        self.FileName = str(path) if path else ""
        self.saved = []
        self.recomputes = 0

    def recompute(self):
        self.recomputes += 1

    def save(self):
        self.saved.append(("save", self.FileName))

    def saveAs(self, path):
        from pathlib import Path

        self.saved.append(("saveAs", path))
        Path(path).write_bytes(b"saved CAD copy")
        self.FileName = path


def choose_file(commands, monkeypatch, result):
    calls = []
    monkeypatch.setattr(
        commands.QtWidgets.QFileDialog,
        "getSaveFileName",
        lambda *args: calls.append(args) or (str(result) if result else "", ""),
        raising=False,
    )
    return calls


@pytest.mark.parametrize("readonly", ["file", "directory"])
def test_readonly_document_prompts_for_copy(commands, monkeypatch, tmp_path, readonly):
    origin = tmp_path / "bundled"
    origin.mkdir()
    source = origin / "Example.FCStd"
    source.write_bytes(b"original CAD")
    destination = tmp_path / "copy"
    document = Document(source)
    blocked = str(source if readonly == "file" else origin)
    monkeypatch.setattr(commands.os, "access", lambda path, mode: str(path) != blocked)
    calls = choose_file(commands, monkeypatch, destination)
    result = commands._save_document(document)
    assert result == str(destination) + ".FCStd"
    assert document.saved == [("saveAs", result)]
    assert document.recomputes == 1
    assert calls[0][1] == "Save a writable FreeCAD copy"
    assert source.read_bytes() == b"original CAD"


def test_writable_document_saves_in_place(commands, monkeypatch, tmp_path):
    source = tmp_path / "working.FCStd"
    source.write_bytes(b"CAD")
    document = Document(source)
    calls = choose_file(commands, monkeypatch, None)
    assert commands._save_document(document) == str(source)
    assert document.saved == [("save", str(source))]
    assert not calls


def test_unsaved_document_prompts_and_recomputes(commands, monkeypatch, tmp_path):
    document = Document(None)
    destination = tmp_path / "New.FCStd"
    calls = choose_file(commands, monkeypatch, destination)
    assert commands._save_document(document) == str(destination)
    assert document.saved == [("saveAs", str(destination))]
    assert document.recomputes == 1
    assert calls[0][1] == "Save FreeCAD document"


def test_cancelled_copy_does_not_create_server_item(commands, monkeypatch, tmp_path):
    source = tmp_path / "example.FCStd"
    source.write_bytes(b"original CAD")
    document = Document(source)
    monkeypatch.setattr(commands.os, "access", lambda path, mode: str(path) != str(source))
    choose_file(commands, monkeypatch, None)
    monkeypatch.setattr(commands.FreeCAD, "ActiveDocument", document)
    calls = []
    client = SimpleNamespace(create_item=lambda *args: calls.append(args))
    monkeypatch.setattr(commands.Session, "require_client", lambda: client)
    errors = []
    monkeypatch.setattr(commands, "error", lambda title, message: errors.append(message))
    commands.UploadCommand().Activated()
    assert errors == ["Save the document before uploading"]
    assert not document.saved
    assert not calls
    assert document.FileName == str(source)


def test_readonly_destination_is_rejected(commands, monkeypatch, tmp_path):
    document = Document(None)
    destination = tmp_path / "unwritable" / "part.FCStd"
    choose_file(commands, monkeypatch, destination)
    monkeypatch.setattr(commands.os, "access", lambda path, mode: False)
    with pytest.raises(RuntimeError, match="Choose a writable location"):
        commands._save_document(document)
    assert not document.saved


def test_save_failure_reports_path_and_recovery(commands, monkeypatch, tmp_path):
    source = tmp_path / "working.FCStd"
    source.write_bytes(b"CAD")
    document = Document(source)

    def fail():
        raise OSError("Failed to open file")

    document.save = fail
    with pytest.raises(RuntimeError, match="working.FCStd.*Failed to open file.*Save As"):
        commands._save_document(document)


@pytest.mark.parametrize("value", ["241205", None])
def test_invalid_or_cancelled_project_does_not_create_item(commands, monkeypatch, value):
    calls, errors = [], []
    document = Document(None)
    monkeypatch.setattr(commands, "_require_document", lambda: document)
    monkeypatch.setattr(commands, "_save_document", lambda doc: "/tmp/example.FCStd")
    monkeypatch.setattr(commands, "_metadata", lambda doc: None)
    monkeypatch.setattr(commands, "ask_choice", lambda *args: "part")
    monkeypatch.setattr(commands, "ask_text", lambda *args: value)
    monkeypatch.setattr(commands, "error", lambda title, message: errors.append(message))
    client = SimpleNamespace(create_item=lambda *args: calls.append(args))
    monkeypatch.setattr(commands.Session, "require_client", lambda: client)
    commands.UploadCommand().Activated()
    assert not calls
    if value is None:
        assert not errors
    else:
        assert len(errors) == 1
        assert "not its project number" in errors[0]
        assert "uuid_parsing" not in errors[0]


def test_project_id_accepts_uuid_and_optional_blank(commands):
    project = "d96e592c-d42c-4c88-8920-2bfa2c944c1f"
    assert commands._project_id("  " + project.upper() + "  ") == project
    assert commands._project_id("   ") is None
