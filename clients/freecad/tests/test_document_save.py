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
    module._test_errors = []

    def run(action):
        workflow = action()
        value = None
        try:
            while True:
                request = workflow.send(value)
                value = request.function(*request.args, **request.kwargs)
        except StopIteration:
            pass
        except Exception as exception:
            module._test_errors.append(str(exception))

    monkeypatch.setattr(module, "_run", run)
    yield module
    for name in set(sys.modules) - before:
        if name == "freecad" or name.startswith("freecad."):
            del sys.modules[name]


class Document:
    Label = "Example"
    Objects = []
    HasPendingTransaction = False

    Name = "ExampleDocument"

    def __init__(self, path):
        self.FileName = str(path) if path else ""
        self.saved = []
        self.recomputes = 0

    def recompute(self):
        self.recomputes += 1

    def getObject(self, name):
        return None

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


def test_successful_addon_save_clears_gui_modified_flag(commands, monkeypatch, tmp_path):
    path = tmp_path / "saved.FCStd"
    path.write_bytes(b"saved")
    document = Document(path)
    gui_document = SimpleNamespace(Modified=True)
    monkeypatch.setattr(
        commands.FreeCADGui, "getDocument", lambda name: gui_document, raising=False
    )
    assert commands._save_document(document) == str(path)
    assert not gui_document.Modified


def test_failed_addon_save_preserves_gui_modified_flag(commands, monkeypatch, tmp_path):
    path = tmp_path / "saved.FCStd"
    path.write_bytes(b"saved")
    document = Document(path)
    gui_document = SimpleNamespace(Modified=True)
    monkeypatch.setattr(
        commands.FreeCADGui, "getDocument", lambda name: gui_document, raising=False
    )

    def fail():
        raise RuntimeError("save failed")

    document.save = fail
    with pytest.raises(RuntimeError, match="Could not save"):
        commands._save_document(document)
    assert gui_document.Modified


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


def test_checkin_uploads_and_releases_without_prompting_for_a_note(commands, monkeypatch):
    document = Document("/tmp/managed.FCStd")
    metadata = SimpleNamespace(RevisionId="revision", ItemId="item")
    calls = []
    client = SimpleNamespace(
        checkin=lambda revision: calls.append(("checkin", revision)),
        get_revision=lambda revision: {"item_id": "item", "item_kind": "assembly"},
    )

    def editable(*args):
        yield from ()

    def ensure_working(*args):
        yield from ()
        return document.FileName

    def upload(*args):
        calls.append(("upload", args[2]))
        yield from ()

    monkeypatch.setattr(commands, "_require_document", lambda: document)
    monkeypatch.setattr(commands, "_require_metadata", lambda doc: metadata)
    monkeypatch.setattr(commands.Session, "require_client", lambda: client)
    monkeypatch.setattr(commands, "_editable", editable)
    monkeypatch.setattr(commands, "_ensure_working", ensure_working)
    monkeypatch.setattr(commands, "_upload_native", upload)
    monkeypatch.setattr(commands.cad, "capture", lambda doc: [])
    monkeypatch.setattr(commands, "ask_text", lambda *args: pytest.fail("unexpected note prompt"))
    monkeypatch.setattr(commands, "information", lambda *args: None)
    commands.CheckInCommand().Activated()
    assert not commands._test_errors
    assert calls == [("upload", document.FileName), ("checkin", "revision")]


def test_tree_refresh_checks_checkout_before_changing_labels(commands, monkeypatch):
    from datetime import datetime, timedelta, timezone

    document = Document("/workspace/working/model.FCStd")
    metadata = SimpleNamespace(RevisionId="revision", ItemId="item")
    client = SimpleNamespace(
        base_url="http://localhost:8000",
        get_revision=lambda revision: {"item_id": "item", "lifecycle_state": "working"},
        get_checkout=lambda revision: {
            "user_id": "other",
            "revision_id": "revision",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        },
    )
    monkeypatch.setattr(commands, "_require_document", lambda: document)
    monkeypatch.setattr(commands, "_require_metadata", lambda doc: metadata)
    monkeypatch.setattr(commands, "_guard_document", lambda *args: document)
    monkeypatch.setattr(commands.Session, "require_client", lambda: client)
    monkeypatch.setattr(commands.Session, "user", {"id": "user"})
    monkeypatch.setattr(commands.workspace, "working_path", lambda *args: object())
    monkeypatch.setattr(
        commands.tree_labels, "refresh", lambda doc: pytest.fail("unauthorized label mutation")
    )
    commands.RefreshTreeLabelsCommand().Activated()
    assert len(commands._test_errors) == 1
    assert "own assembly checkout" in commands._test_errors[0]
    assert not document.saved


def test_unsaved_document_prompts_and_recomputes(commands, monkeypatch, tmp_path):
    document = Document(None)
    destination = tmp_path / "New.FCStd"
    calls = choose_file(commands, monkeypatch, destination)
    assert commands._save_document(document) == str(destination)
    assert document.saved == [("saveAs", str(destination))]
    assert document.recomputes == 1
    assert calls[0][1] == "Save FreeCAD document"


def test_cancelled_workspace_does_not_create_server_item(commands, monkeypatch, tmp_path):
    source = tmp_path / "example.FCStd"
    source.write_bytes(b"original CAD")
    document = Document(source)
    monkeypatch.setattr(commands.os, "access", lambda path, mode: str(path) != str(source))
    choose_file(commands, monkeypatch, None)
    monkeypatch.setattr(commands.FreeCAD, "ActiveDocument", document)
    calls = []
    client = SimpleNamespace(
        create_item=lambda *args: calls.append(args),
        base_url="http://localhost:8000",
        validate_references=lambda references: [],
        list_projects=lambda **kwargs: {
            "items": [{"id": "project", "project_number": "TEST", "name": "Test"}],
            "limit": 50,
            "offset": 0,
            "has_more": False,
        },
    )
    monkeypatch.setattr(commands.Session, "require_client", lambda: client)
    errors = commands._test_errors
    monkeypatch.setattr(commands, "ask_choice", lambda title, prompt, choices, *args: choices[0])
    monkeypatch.setattr(commands, "_guard_document", lambda *args: document)
    monkeypatch.setattr(commands, "_choose_workspace", lambda *args: None)
    commands.UploadCommand().Activated()
    assert not errors
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


def test_cancelled_project_does_not_create_item(commands, monkeypatch):
    calls = []
    document = Document(None)
    monkeypatch.setattr(commands, "_require_document", lambda: document)
    monkeypatch.setattr(commands, "_metadata", lambda doc: None)
    monkeypatch.setattr(
        commands,
        "ask_choice",
        lambda title, *args: "part" if title == "New ForgePDM Item" else None,
    )
    client = SimpleNamespace(
        create_item=lambda *args: calls.append(args),
        list_projects=lambda **kwargs: {
            "items": [{"id": "project", "project_number": "TEST", "name": "Test"}],
            "limit": 50,
            "offset": 0,
            "has_more": False,
        },
    )
    monkeypatch.setattr(commands.Session, "require_client", lambda: client)
    commands.UploadCommand().Activated()
    assert not calls
    assert not commands._test_errors
    assert not document.saved


def test_project_id_accepts_uuid_and_optional_blank(commands):
    project = "d96e592c-d42c-4c88-8920-2bfa2c944c1f"
    assert commands._project_id("  " + project.upper() + "  ") == project
    assert commands._project_id("   ") is None


def test_logout_accepts_already_expired_server_session(commands, monkeypatch):
    client = SimpleNamespace(logout=lambda: None)
    monkeypatch.setattr(commands.Session, "clear", lambda: client)
    messages = []
    monkeypatch.setattr(commands, "information", lambda title, message: messages.append(message))
    workflow = commands.LogoutCommand().action()
    next(workflow)
    with pytest.raises(StopIteration):
        workflow.throw(commands.ForgePDMError("expired", 401))
    assert messages == ["Logged out"]


def test_managed_save_rebases_external_links_after_filename_changes(commands, tmp_path):
    from types import SimpleNamespace

    document = Document(tmp_path / "original.FCStd")
    target = SimpleNamespace(Document=object())
    events = []

    class Link:
        Name = "Link"
        TypeId = "App::Link"
        LinkedObject = target
        Placement = object()

        def setLink(self, value):
            events.append((document.FileName, value))
            self.LinkedObject = value

    document.Objects = [Link()]
    document.getObject = lambda name: document.Objects[0]
    destination = tmp_path / "working.FCStd"
    placement = document.Objects[0].Placement
    commands._save_managed_as(document, str(destination))
    assert events == [(str(destination), None), (str(destination), target)]
    assert document.Objects[0].Placement is placement
    assert document.saved == [("saveAs", str(destination)), ("save", str(destination))]


def test_reference_change_during_preparation_stops_before_upload(commands, monkeypatch):
    from types import SimpleNamespace

    document = Document(None)
    monkeypatch.setattr(commands.cad, "capture", lambda doc: [{"changed": True}])
    workflow = commands._upload_native(SimpleNamespace(), document, "unused.FCStd", [])
    with pytest.raises(commands.workspace.WorkspaceError, match="references changed"):
        next(workflow)


def test_new_revision_opens_distinct_document_and_preserves_live_parent_targets(
    commands, monkeypatch, tmp_path
):
    source = Document(tmp_path / "source.FCStd")
    source_metadata = SimpleNamespace(
        ItemId="item", ItemNumber="PART", RevisionId="A", RevisionLabel="A"
    )
    source.getObject = lambda name: source_metadata
    clone = Document(tmp_path / "new.FCStd")
    clone.Name = "NewRevision"
    clone.HasPendingTransaction = True
    clone.commitTransaction = lambda: setattr(clone, "HasPendingTransaction", False)
    clone_metadata = SimpleNamespace(
        ItemId="item", ItemNumber="PART", RevisionId="A", RevisionLabel="A"
    )
    clone.getObject = lambda name: clone_metadata
    parent = SimpleNamespace(LinkedObject=SimpleNamespace(Document=source))
    events = []
    client = SimpleNamespace(
        base_url="http://forgepdm.test",
        get_item=lambda item: {
            "current_revision_id": "A",
            "current_revision": {"lifecycle_state": "released"},
        },
        validate_references=lambda refs: None,
        prepare_working=lambda root: clone.FileName,
        copy_revision_source=lambda *args: events.append(("copy", args)),
        create_next_revision=lambda *args: {"id": "B", "label": "B"},
    )
    monkeypatch.setattr(commands.Session, "require_client", lambda: client)
    monkeypatch.setattr(commands, "_require_document", lambda: source)
    monkeypatch.setattr(commands, "_guard_document", lambda *args: source)
    monkeypatch.setattr(commands, "ask_text", lambda *args: "New geometry")
    monkeypatch.setattr(commands, "_choose_workspace", lambda *args: str(tmp_path))
    monkeypatch.setattr(commands.cad, "document_modified", lambda doc: False)
    monkeypatch.setattr(commands.cad, "capture", lambda doc: [])
    monkeypatch.setattr(commands.FreeCAD, "openDocument", lambda path: clone, raising=False)
    monkeypatch.setattr(
        commands.FreeCAD,
        "setActiveDocument",
        lambda name: events.append(("active", name)),
        raising=False,
    )
    monkeypatch.setattr(
        commands,
        "_set_metadata",
        lambda doc, **values: vars(doc.getObject("metadata")).update(values),
    )
    monkeypatch.setattr(commands, "_save_document", lambda doc: events.append(("save", doc)))

    def upload(client, doc, path, refs):
        events.append(("upload", doc))
        yield from ()

    monkeypatch.setattr(commands, "_upload_native", upload)
    monkeypatch.setattr(commands, "information", lambda *args: None)
    commands.NewRevisionCommand().Activated()
    assert not commands._test_errors
    assert source_metadata.RevisionId == "A"
    assert source.FileName == str(tmp_path / "source.FCStd")
    assert parent.LinkedObject.Document is source
    assert clone_metadata.RevisionId == "B"
    assert not clone.HasPendingTransaction
    assert ("upload", clone) in events
    assert not source.saved


@pytest.mark.parametrize("dirty", [True, False])
def test_new_revision_rejects_dirty_or_historical_source_before_server_mutation(
    commands, monkeypatch, dirty
):
    source = Document("/tmp/source.FCStd")
    source.getObject = lambda name: SimpleNamespace(
        ItemId="item", ItemNumber="PART", RevisionId="A", RevisionLabel="A"
    )
    client = SimpleNamespace(get_item=lambda item: {"current_revision_id": "B"})
    monkeypatch.setattr(commands.Session, "require_client", lambda: client)
    monkeypatch.setattr(commands, "_require_document", lambda: source)
    monkeypatch.setattr(commands.cad, "document_modified", lambda doc: dirty)
    monkeypatch.setattr(commands, "ask_text", lambda *args: "New revision")
    commands.NewRevisionCommand().Activated()
    assert len(commands._test_errors) == 1
    assert not source.saved


def test_bom_notice_preserves_pinned_revision_and_multilevel_formatting(commands):
    child = {
        "position": 1,
        "item_number": "PART",
        "item_name": "Part",
        "revision_label": "A",
        "quantity": "2",
        "lifecycle_state": "released",
        "component_revision_id": "part-A",
    }
    parent = dict(child, item_number="SUB", component_revision_id="sub-A", children=[child])
    text = commands._format_bom([parent], updates={"part-A": "B"})
    assert "PART Part RevA  x2  released  [Newer revision available: B]" in text
    assert "\n  1. PART" in text
    assert child["revision_label"] == "A"


@pytest.mark.parametrize("fault", ["dirty", "released", "checkout"])
def test_replace_revision_guards_parent_before_loading_replacement(commands, monkeypatch, fault):
    document = Document("/tmp/working/model.FCStd")
    metadata = SimpleNamespace(
        ItemId="assembly", ItemNumber="ASM", RevisionId="assembly-A", RevisionLabel="A"
    )
    document.getObject = lambda name: metadata
    client = SimpleNamespace(
        get_revision=lambda key: {
            "item_id": "assembly",
            "lifecycle_state": "released" if fault == "released" else "working",
        }
    )
    monkeypatch.setattr(commands.Session, "require_client", lambda: client)
    monkeypatch.setattr(commands, "_require_document", lambda: document)
    monkeypatch.setattr(commands.cad, "document_modified", lambda doc: fault == "dirty")

    def authorize(*args):
        raise commands.workspace.WorkspaceError("Acquire your own checkout")
        yield

    monkeypatch.setattr(commands, "_authorize_tree_labels", authorize)
    commands.ReplaceRevisionCommand().Activated()
    assert len(commands._test_errors) == 1
    assert not document.saved


def test_target_mapping_groups_repeated_occurrences_and_cancellation(commands, monkeypatch):
    from freecad.forgepdm import replacement

    source = Document("/tmp/source.FCStd")
    source.getObject = lambda name: SimpleNamespace(TypeId="App::Link")
    target = SimpleNamespace(Name="DifferentBody", Label="New Body", TypeId="PartDesign::Body")
    target_doc = SimpleNamespace()
    monkeypatch.setattr(replacement, "target_objects", lambda doc: [target])
    refs = [{"object_name": name, "target_object_name": "OldBody"} for name in ("First", "Repeat")]
    calls = []
    monkeypatch.setattr(commands, "ask_choice", lambda *args: calls.append(args) or args[2][0])
    assert commands._map_replacement_objects(source, refs, ["First", "Repeat"], target_doc) == {
        "First": "DifferentBody",
        "Repeat": "DifferentBody",
    }
    assert len(calls) == 1
    monkeypatch.setattr(commands, "ask_choice", lambda *args: None)
    assert commands._map_replacement_objects(source, refs, ["First"], target_doc) is None
