"""Tree collection and language fencing with fake CAD; no GUI or vendor imports."""

from concurrent.futures import Future
import importlib.util
import json
import sys
from types import ModuleType, SimpleNamespace as NS
from uuid import uuid4

import pytest
from test_fasteners import bolt

from freecad.forgepdm import fasteners
from freecad.forgepdm.jobs import Context
from freecad.forgepdm.session import Session


@pytest.fixture
def tree_module(monkeypatch, addon_root):
    app, gui, ui = (
        ModuleType("FreeCAD"),
        ModuleType("FreeCADGui"),
        ModuleType("freecad.forgepdm.ui"),
    )
    app.listDocuments = lambda: {}
    ui.QtCore, ui.QtGui = NS(), NS()
    ui.QtWidgets = NS(QStyledItemDelegate=object, QApplication=NS(activeModalWidget=lambda: None))
    monkeypatch.setitem(sys.modules, "FreeCAD", app)
    monkeypatch.setitem(sys.modules, "FreeCADGui", gui)
    monkeypatch.setitem(sys.modules, "freecad.forgepdm.ui", ui)
    spec = importlib.util.spec_from_file_location(
        "freecad.forgepdm._tree_test", addon_root / "freecad/forgepdm/tree_status.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_collect_fasteners_inside_containers_without_changing_status_ownership(
    tree_module, monkeypatch
):
    tree = tree_module
    client = NS(base_url="http://server")
    assembly = NS(Name="Assembly", TypeId="App::Part")
    obj = bolt()
    obj.Label = "M8x25-Screw"
    obj.InList = [assembly]
    obj.isDerivedFrom = lambda _: True
    revision = str(uuid4())
    fasteners.associate(obj, revision)
    source_revision = str(uuid4())
    metadata = NS(
        ItemId=str(uuid4()),
        RevisionId=source_revision,
        ServerUrl=client.base_url,
        PDMDescriptionData=json.dumps(
            dict(version=2, revision_id=source_revision, description="Assembly description")
        ),
    )
    document = NS(Name="Fixture", FileName="", Objects=[assembly, obj])
    document.getObject = lambda name: (
        metadata
        if name == "ForgePDM_Metadata"
        else next((o for o in document.Objects if o.Name == name), None)
    )
    obj.Document = assembly.Document = document
    monkeypatch.setattr(tree.App, "listDocuments", lambda: {document.Name: document})
    monkeypatch.setattr(tree.cad, "document_modified", lambda _: True)
    targets, rows = tree.collect(client)
    key = rows[(document.Name, obj.Name)]
    assert key == rows[(document.Name, "")]
    assert targets[key]["revision_id"] == source_revision
    assert targets[key]["fasteners"][obj.Name]["revision_id"] == revision
    assert "ISO4017" in targets[key]["fasteners"][obj.Name]["description"]
    obj.Length = "30"
    targets, rows = tree.collect(client)
    assert targets[key]["fasteners"][obj.Name]["revision_id"] is None
    assert "30" in targets[key]["fasteners"][obj.Name]["description"]
    obj.Proxy = None
    targets, _ = tree.collect(client)
    assert targets[key]["fasteners"][obj.Name] == dict(revision_id=None, description=obj.Label)


def test_language_change_rejects_pending_result_without_rebuilding_columns(
    tree_module, monkeypatch
):
    tree = tree_module
    client = NS(
        token="memory",
        description_language="pt-BR",
        is_expired=lambda: False,
        fetch_tree_status=lambda *a: None,
    )
    monkeypatch.setattr(Session, "client", client)
    monkeypatch.setattr(Session, "user", {"id": "actor"})
    monkeypatch.setattr(Session, "busy", False)
    paints, requests = [], []
    pending = Future()
    controller = tree.Controller.__new__(tree.Controller)
    controller.column = NS(render=lambda *args: paints.append(args))
    controller.future, controller.context = pending, Context()
    cancelled = controller.context
    controller.key, controller.language, controller.generation = tree.session_key(), "pt-BR", 1
    controller.request_key, controller.request_generation = controller.key, 1
    controller.snapshot, controller.hash_cache = {"language": "pt-BR"}, {}
    controller.pending, controller.next_refresh, controller.next_paint, controller.stale = (
        False,
        1e20,
        0,
        None,
    )
    controller.executor = NS(submit=lambda *args: requests.append(args) or Future())
    monkeypatch.setattr(tree, "collect", lambda client: ({"doc": {"foreign": False}}, {}))
    pending.set_result({"language": "pt-BR", "remote": {"obsolete-language": {}}})
    client.description_language = "en"
    controller._tick()
    assert cancelled.cancelled.is_set()
    assert controller.snapshot is None and controller.language == "en"
    assert paints[0][1] is None and len(requests) == 1
    assert controller.request_generation == 2
