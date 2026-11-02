"""Loader metadata saves must not leave false dirty flags or discard real edits."""

import sys
from types import ModuleType, SimpleNamespace as NS

import pytest

from freecad.forgepdm import cad
from freecad.forgepdm.workspace import WorkspaceError


@pytest.fixture
def configuration_gui(tmp_path, monkeypatch):
    path = tmp_path / "documents/component.FCStd"
    path.parent.mkdir()
    path.write_bytes(b"downloaded native bytes")
    gui_document = NS(Modified=False)
    document = NS(
        Name="Component",
        Label="Component",
        FileName=str(path),
        isTouched=lambda: False,
        recompute=lambda: None,
        getObject=lambda name: None,
        HasPendingTransaction=False,
    )
    opened, closed, saves = {}, [], []

    def gui_save():
        saves.append(document.Name)
        gui_document.Modified = False

    gui_document.save = gui_save
    app = ModuleType("FreeCAD")
    app.listDocuments = lambda: opened
    app.openDocument = lambda filename: opened.setdefault(document.Name, document)
    app.getDocument = lambda name: opened.get(name)
    app.setActiveDocument = lambda name: None
    app.closeDocument = lambda name: closed.append(name)
    gui = ModuleType("FreeCADGui")
    gui.getDocument = lambda name: gui_document
    monkeypatch.setitem(sys.modules, "FreeCAD", app)
    monkeypatch.setitem(sys.modules, "FreeCADGui", gui)

    def metadata(doc, **values):
        # Match FreeCAD: recomputed objects can be untouched while GUI stays dirty.
        gui_document.Modified = True

    configuration = {
        "directory": str(tmp_path),
        "ledger": {
            "server_url": "http://forgepdm.test",
            "order": ["file"],
            "root_file_id": "file",
            "documents": [
                {
                    "file_id": "file",
                    "path": "documents/component.FCStd",
                    "item_id": "item",
                    "revision_id": "revision",
                    "item_number": "P1",
                    "revision_label": "A",
                    "references": [],
                }
            ],
        },
    }
    return NS(
        configuration=configuration,
        metadata=metadata,
        document=document,
        gui=gui_document,
        opened=opened,
        closed=closed,
        saves=saves,
    )


def test_retrieval_metadata_save_leaves_clean_gui_state(configuration_gui):
    case = configuration_gui
    result = cad.open_configuration(case.configuration, case.metadata)
    assert result["root"] is case.document
    assert case.saves == ["Component"]
    assert not cad.document_modified(case.document)
    assert not case.closed


def test_legacy_label_projection_is_recomputed_before_save(configuration_gui, monkeypatch):
    case = configuration_gui
    touched = [False]
    recomputes = []

    def recompute():
        touched[0] = False
        recomputes.append(True)

    def add_label_metadata(document):
        touched[0] = True
        return {"changed": True}

    original_save = case.gui.save

    def save():
        assert not touched[0], "Label metadata was saved without recomputing it"
        original_save()

    case.document.isTouched = lambda: touched[0]
    case.document.recompute = recompute
    case.gui.save = save
    monkeypatch.setattr(cad.tree_labels, "refresh", add_label_metadata)
    result = cad.open_configuration(case.configuration, case.metadata)
    assert result["root"] is case.document
    assert len(recomputes) == 2
    assert not cad.document_modified(case.document)


def test_unresolved_touch_after_label_projection_still_rejects_configuration(
    configuration_gui, monkeypatch
):
    case = configuration_gui
    case.document.isTouched = lambda: True
    monkeypatch.setattr(cad.tree_labels, "refresh", lambda document: {"changed": True})
    with pytest.raises(WorkspaceError, match="could not be saved cleanly"):
        cad.open_configuration(case.configuration, case.metadata)
    assert not case.closed


def test_real_edit_after_download_is_still_dirty_and_retained(configuration_gui):
    case = configuration_gui
    result = cad.open_configuration(case.configuration, case.metadata)
    case.gui.Modified = True
    assert not case.document.isTouched()  # A recompute can clear touched state.
    assert cad.document_modified(case.document)
    assert cad.close_owned(result["owned"]) == ["Component"]
    assert not case.closed


@pytest.mark.parametrize("failure", ["still_dirty", "exception"])
def test_failed_save_does_not_publish_clean_state_or_close_dirty_document(
    configuration_gui, failure
):
    case = configuration_gui

    def fail_save():
        if failure == "exception":
            raise OSError("Save failed")

    case.gui.save = fail_save
    with pytest.raises((WorkspaceError, OSError)):
        cad.open_configuration(case.configuration, case.metadata)
    assert case.gui.Modified
    assert not case.closed
