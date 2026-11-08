"""Real FreeCAD/native-tree/HTTP acceptance using only disposable fixture data."""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from uuid import uuid4

import FreeCAD as App
import FreeCADGui as Gui
import freecad.forgepdm as package
from freecad.forgepdm import cad as installed_cad, tree_status as installed_status
from freecad.forgepdm.ui import QtWidgets

repo = Path("/home/ricardoblank/Development/ForgePDM")
case = Path("/tmp/forgepdm-simple-description-qa")
config = json.loads((case / "connection.json").read_text())
browser = json.loads((case / "materials-browser-report.json").read_text())
checks = []
owned = []


def load(name, filename):
    spec = importlib.util.spec_from_file_location(
        "freecad.forgepdm." + name, repo / "clients/freecad/freecad/forgepdm" / filename
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def state():
    return {
        d.Name: (
            d.FileName,
            installed_cad.document_modified(d),
            d.isTouched(),
            hashlib.sha256(Path(d.FileName).read_bytes()).hexdigest()
            if d.FileName and Path(d.FileName).is_file()
            else None,
        )
        for d in App.listDocuments().values()
    }


def metadata(document, **values):
    obj = document.getObject("ForgePDM_Metadata")
    if obj is None:
        obj = document.addObject("App::FeaturePython", "ForgePDM_Metadata")
    for key, value in values.items():
        if not hasattr(obj, key):
            obj.addProperty("App::PropertyString", key, "ForgePDM")
        setattr(obj, key, str(value))
    return obj


def identify(document, item):
    return metadata(
        document,
        ItemId=item["id"],
        RevisionId=item["current_revision_id"],
        ItemNumber=item["number"],
        RevisionLabel="A",
        ServerUrl=client.base_url,
    )


def publish(document, item, references=None):
    filename = case / (document.Name + ".FCStd")
    document.recompute()
    document.saveAs(str(filename))
    Gui.getDocument(document.Name).save()
    data = filename.read_bytes()
    lease = client.get_checkout(item["current_revision_id"])
    intent = {
        "revision_id": item["current_revision_id"],
        "operation_id": str(uuid4()),
        "expected_checkout_id": lease["id"],
        "expected_checkout_version": lease["version"],
        "content_hash": hashlib.sha256(data).hexdigest(),
        "byte_size": len(data),
        "references": references or [],
    }
    result = client.upload_part_checkin(str(filename), intent)
    assert client.upload_part_checkin(str(filename), intent) == result
    return result


previous_description = sys.modules.get("freecad.forgepdm.descriptions")
previous_attribute = getattr(package, "descriptions", None)
previous_controller = installed_status._controller
before = state()
active = App.ActiveDocument.Name if App.ActiveDocument else None
column = None
try:
    if previous_controller:
        previous_controller.timer.stop()
        previous_controller.column.clear()
    descriptions = load("descriptions", "descriptions.py")
    package.descriptions = descriptions
    api = load("_simple_api_fixture", "api.py")
    source_cad = load("_simple_cad_fixture", "cad.py")
    workspace = load("_simple_workspace_fixture", "workspace.py")
    tree = load("_simple_tree_fixture", "tree_status.py")
    client = api.ForgePDMClient(config["url"])
    client.login("web-admin", config["password"])
    p = client.create_item("part", "Simple material part " + uuid4().hex[:6])
    part = App.newDocument("SimplePart" + uuid4().hex[:8])
    owned.append(part)
    solid = part.addObject("Part::Box", "Solid")
    part.recompute()
    pm = identify(part, p)
    material = client.get_description(browser["materialRevision"])
    descriptions.apply(
        part,
        pm,
        client.get_description(p["current_revision_id"]),
        material["description"],
        browser["materialRevision"],
    )
    part_result = publish(part, p)
    assert (
        client.get_description(p["current_revision_id"])["description"] == material["description"]
    )
    checks.append(
        "part material description publishes atomically without density or quantities; replay is safe"
    )
    a = client.create_item("assembly", "Simple assembly " + uuid4().hex[:6])
    assembly = App.newDocument("SimpleAssembly" + uuid4().hex[:8])
    owned.append(assembly)
    assembly.saveAs(str(case / (assembly.Name + ".FCStd")))
    component = assembly.addObject("App::Link", "Component")
    component.setLink(solid)
    am = identify(assembly, a)
    descriptions.apply(
        assembly, am, client.get_description(a["current_revision_id"]), "General mounting"
    )
    assembly.recompute()
    reference = {
        "object_name": "Component",
        "property_name": "LinkedObject",
        "target_revision_id": p["current_revision_id"],
        "target_dataset_id": part_result["dataset"]["id"],
        "target_file_id": part_result["dataset"]["files"][0]["id"],
        "target_object_name": "Solid",
    }
    result = publish(assembly, a, [reference])
    checks.append("assembly free text publishes with its pinned component references")
    ids = [p["current_revision_id"], a["current_revision_id"]]
    remote = client._json_request("POST", "/api/v1/status/revisions", {"revision_ids": ids})
    column = tree.Column()
    column.render(
        client,
        {
            "remote": {r["revision_id"]: r for r in remote["items"]},
            "checked_at": remote["checked_at"],
        },
    )
    Gui.updateGui()
    texts = []
    for widget in Gui.getMainWindow().findChildren(QtWidgets.QTreeWidget):
        if widget.metaObject().className() != "Gui::TreeWidget":
            continue
        assert (
            widget.headerItem().text(3) == "PDM status"
            and widget.headerItem().text(4) == "Description"
        )
        assert [
            widget.headerItem().text(i)
            for i in range(widget.columnCount())
            if not widget.isColumnHidden(i)
        ].count("Description") == 1
        iterator = QtWidgets.QTreeWidgetItemIterator(widget)
        while iterator.value():
            texts.append(iterator.value().text(4))
            iterator += 1
    assert "General mounting" in texts and material["description"] in texts, texts
    assert component.Label == "Component"
    checks.append(
        "native tree shows assembly text and linked part material in one Description column beside unchanged PDM status"
    )
    column.clear()
    column = None
    for document in reversed(owned):
        App.closeDocument(document.Name)
    owned = []
    configuration = workspace.retrieve(
        client,
        str(case / "workspace"),
        a["current_revision_id"],
        result["dataset"]["id"],
        result["dataset"]["files"][0]["id"],
    )
    opened = source_cad.open_configuration(configuration, metadata)
    owned.extend(opened["owned"])
    workspace.finish(client, configuration)
    restored = opened["root"]
    restored_part = restored.getObject("Component").LinkedObject.Document
    assert restored.getObject("ForgePDM_Metadata").PDMDescription == "General mounting"
    assert restored_part.getObject("ForgePDM_Metadata").PDMDescription == material["description"]
    assert (
        json.loads(restored_part.getObject("ForgePDM_Metadata").PDMDescriptionData)[
            "material_revision_id"
        ]
        == browser["materialRevision"]
    )
    checks.append(
        "download and native reopen preserve assembly description and exact part material revision"
    )
    report = {
        "runtime": App.Version()[:3],
        "checks": checks,
        "scope": "Disposable API and documents only",
    }
    (case / "simple-descriptions-freecad-report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))
finally:
    if column:
        column.clear()
    for document in reversed(owned):
        if document.Name in App.listDocuments():
            App.closeDocument(document.Name)
    if previous_description is None:
        sys.modules.pop("freecad.forgepdm.descriptions", None)
    else:
        sys.modules["freecad.forgepdm.descriptions"] = previous_description
    if previous_attribute is None:
        if hasattr(package, "descriptions"):
            delattr(package, "descriptions")
    else:
        package.descriptions = previous_attribute
    if active and active in App.listDocuments():
        App.setActiveDocument(active)
    if previous_controller:
        previous_controller.timer.start()
    assert state() == before, "existing user document state changed"
