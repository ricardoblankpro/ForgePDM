"""Real GUI registration/linking, native mass, replay and portable retrieval."""

import hashlib
import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import FreeCAD as App
import FreeCADGui as Gui
import Materials
import freecad.forgepdm as package
from freecad.forgepdm import cad as old_cad, commands as old_commands, tree_status
from freecad.forgepdm.ui import QtCore, QtWidgets
from freecad.forgepdm.jobs import Context

repo = Path("/home/ricardoblank/Development/ForgePDM")
case = Path(globals().get("MATERIAL_PHYSICAL_QA_CASE", "/tmp/forgepdm-physical-material-qa"))
config = json.loads((case / "connection.json").read_text())
checks = []
owned = []
old_session = (old_commands.Session.client, old_commands.Session.user)
old_active = App.ActiveDocument.Name if App.ActiveDocument else None
previous_controller = tree_status._controller
before = {
    d.Name: (
        d.FileName,
        old_cad.document_modified(d),
        d.isTouched(),
        hashlib.sha256(Path(d.FileName).read_bytes()).hexdigest()
        if d.FileName and Path(d.FileName).is_file()
        else None,
    )
    for d in App.listDocuments().values()
}
previous = {
    name: (sys.modules.get("freecad.forgepdm." + name), getattr(package, name, None))
    for name in ("physical_materials", "descriptions")
}
observer = None


def load(name, filename):
    spec = importlib.util.spec_from_file_location(
        "freecad.forgepdm." + name, repo / "clients/freecad/freecad/forgepdm" / filename
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def drive(generator):
    try:
        request = next(generator)
    except StopIteration as done:
        return done.value
    while True:
        result = request.execute(Context())
        try:
            request = generator.send(result)
        except StopIteration as done:
            return done.value


def choose_card():
    for dialog in QtWidgets.QApplication.topLevelWidgets():
        if (
            isinstance(dialog, QtWidgets.QDialog)
            and dialog.isVisible()
            and dialog.windowTitle() in ("Register Raw Material", "Link Physical Material")
        ):
            if dialog.windowTitle() == "Register Raw Material":
                dialog.layout().itemAt(0, QtWidgets.QFormLayout.FieldRole).widget().setText(
                    "C15 BAR — GUI PHYSICAL TEST"
                )
            combo = dialog.findChild(QtWidgets.QComboBox)
            index = next(
                i
                for i in range(combo.count())
                if combo.itemData(i)["source_uuid"] == "06ae5c92-de7b-46c9-984d-4dd87964bc5c"
            )
            combo.setCurrentIndex(index)
            dialog.accept()
            return
    QtCore.QTimer.singleShot(50, choose_card)


def select_record(*args, **kwargs):
    yield from ()
    return selected_item


def spin(predicate):
    loop = QtCore.QEventLoop()
    timer = QtCore.QTimer()
    timer.setInterval(50)
    timer.timeout.connect(lambda: loop.quit() if predicate() else None)
    timer.start()
    QtCore.QTimer.singleShot(3000, loop.quit)
    loop.exec_()
    timer.stop()
    assert predicate()


try:
    if previous_controller:
        previous_controller.timer.stop()
        previous_controller.column.clear()
    physical = load("physical_materials", "physical_materials.py")
    package.physical_materials = physical
    descriptions = load("descriptions", "descriptions.py")
    package.descriptions = descriptions
    api = load("_physical_api_fixture", "api.py")
    workspace = load("_physical_workspace_fixture", "workspace.py")
    cad = load("_physical_cad_fixture", "cad.py")
    commands = load("_physical_commands_fixture", "commands.py")
    observed = load("_physical_observer_fixture", "tree_observer.py")
    client = api.ForgePDMClient(config["url"])
    user = client.login("web-admin", config["password"])
    commands.Session.set_client(client, user)
    commands.information = lambda *args: None
    QtCore.QTimer.singleShot(50, choose_card)
    drive(commands.RegisterRawMaterialCommand().action())
    selected_item = client.search_items(query="C15 BAR — GUI PHYSICAL TEST", number_series="M")[
        "items"
    ][-1]
    link = client.get_physical_link(selected_item["current_revision_id"])
    assert link["physical_material"]["density_kg_m3"] == "7800"
    checks.append(
        "real two-field registration dialog creates an M item linked to native material and density"
    )
    unlinked = client.create_item(
        "part", "Existing unlinked M", None, description="Existing unlinked M", number_series="M"
    )
    commands._select_record = select_record
    registered = selected_item
    selected_item = client.search_items(query=unlinked["number"], number_series="M")["items"][0]
    QtCore.QTimer.singleShot(50, choose_card)
    drive(commands.LinkPhysicalMaterialCommand().action())
    assert (
        client.get_physical_link(unlinked["current_revision_id"])["physical_material"][
            "density_kg_m3"
        ]
        == "7800"
    )
    checks.append(
        "existing description-only catalog entry links through the native material dialog"
    )
    selected_item = registered
    item = client.create_item("part", "Native physical mass test")
    document = App.newDocument("PhysicalMass" + uuid4().hex[:8])
    owned.append(document)
    body = document.addObject("PartDesign::Body", "Body")
    box = body.newObject("PartDesign::AdditiveBox", "Solid")
    box.Length = 100
    box.Width = 100
    box.Height = 100
    commands._set_metadata(
        document,
        ItemId=item["id"],
        RevisionId=item["current_revision_id"],
        ItemNumber=item["number"],
        RevisionLabel="A",
        ServerUrl=client.base_url,
    )
    document.recompute()
    path = workspace.prepare_working(client.base_url, str(case / "workspace"))
    document.saveAs(path)
    Gui.getDocument(document.Name).save()
    # Reproduce an old open working copy after a web material assignment.
    current = client.get_description(item["current_revision_id"])
    updated = client._json_request(
        "PUT",
        "/api/v1/revisions/" + item["current_revision_id"] + "/description",
        {
            "description": client.get_description(selected_item["current_revision_id"])[
                "description"
            ],
            "material_revision_id": selected_item["current_revision_id"],
            "expected_token": current["token"],
        },
    )
    metadata = document.getObject("ForgePDM_Metadata")
    metadata.addProperty("App::PropertyString", "PDMDescriptionData", "ForgePDM")
    metadata.PDMDescriptionData = json.dumps(
        {
            "version": 1,
            "revision_id": metadata.RevisionId,
            "description": updated["description"],
            "material_revision_id": updated["material_revision_id"],
            "expected_token": "legacy-description-token",
        }
    )
    assert not getattr(metadata, "PDMPartPhysicalData", "")
    drive(commands._upload_native(client, document, path, []))
    assert abs(
        Decimal(client.get_part_mass(item["current_revision_id"])["mass_kg"]) - Decimal("7.8")
    ) < Decimal("1e-9")
    assert descriptions.local(document)["version"] == 2
    checks.append(
        "legacy open copy with server-assigned physical material upgrades and uploads without reselection"
    )
    commands.ask_choice = lambda *args, **kwargs: "Select material"
    drive(commands.AssignMaterialsCommand().action())
    metadata = document.getObject("ForgePDM_Metadata")
    binding = link["physical_material"]
    assert body.ShapeMaterial.UUID == physical.native_uuid(binding)
    assert abs(Decimal(metadata.PDMPartMassKg) - Decimal("7.8")) < Decimal("1e-9")
    checks.append(
        "selecting one M entry assigns native Body material and calculates 7.8 kg without double-counting its feature"
    )
    observer = observed.TreeObserver()
    App.addDocumentObserver(observer)
    observed.allow_edit(document, client.get_checkout(item["current_revision_id"]), client, user)
    box.Length = 200
    document.recompute()
    spin(lambda: abs(Decimal(metadata.PDMPartMassKg or "0") - Decimal("15.6")) < Decimal("1e-9"))
    checks.append("owned-document geometry recompute automatically updates mass to 15.6 kg")
    result = drive(commands._upload_native(client, document, path, []))
    mass = client.get_part_mass(item["current_revision_id"])
    assert abs(Decimal(mass["mass_kg"]) - Decimal("15.6")) < Decimal("1e-9")
    assert mass["content_hash"] == result["files"][0]["content_hash"]
    drive(commands.CheckInCommand().action())
    checks.append(
        "upload and atomic check-in publish material/density/mass with the exact CAD source hash"
    )
    datasets = client.list_datasets(item["current_revision_id"])
    latest = datasets[0]
    # Pick the actual latest publication rather than relying on list ordering.
    mass = client.get_part_mass(item["current_revision_id"])
    latest = next(d for d in datasets if d["id"] == mass["dataset_id"])
    App.closeDocument(document.Name)
    owned = []
    # Remove only this test's generated cache card, simulating a receiving machine.
    manager = Materials.MaterialManager()
    cached = manager.getMaterial(physical.native_uuid(binding))
    directory = Path(cached.LibraryRoot) / cached.Directory
    files = list(directory.glob("*.FCMat"))
    assert len(files) == 1 and "ForgePDM" in directory.parts
    saved_card = files[0].read_text()
    files[0].unlink()
    manager.refresh()
    assert not files[0].exists()
    configuration = workspace.retrieve(
        client,
        str(case / "receiving-workspace"),
        item["current_revision_id"],
        latest["id"],
        latest["files"][0]["id"],
    )
    opened = cad.open_configuration(configuration, commands._set_metadata)
    owned.extend(opened["owned"])
    workspace.finish(client, configuration)
    restored = opened["root"]
    restored_body = restored.getObject("Body")
    assert files[0].exists(), "managed cache card was not regenerated"
    assert restored_body.ShapeMaterial.UUID == physical.native_uuid(binding)
    assert physical.density(restored_body.ShapeMaterial) == "7800"
    assert abs(
        Decimal(restored.getObject("ForgePDM_Metadata").PDMPartMassKg) - Decimal("15.6")
    ) < Decimal("1e-9")
    checks.append(
        "download/reopen rebuilds a missing managed material cache and preserves frozen native density and mass"
    )
    # Clear the local assignment without touching server records or original cards.
    metadata = restored.getObject("ForgePDM_Metadata")
    descriptions.apply(
        restored, metadata, client.get_description(item["current_revision_id"]), "", None, None
    )
    assert metadata.PDMPartMassKg == "" and not restored_body.ShapeMaterial.hasPhysicalProperty(
        "Density"
    )
    checks.append(
        "clearing a material removes its native density and marks mass unavailable rather than zero"
    )
    report = {
        "runtime": App.Version()[:3],
        "checks": checks,
        "part_id": item["id"],
        "revision_id": item["current_revision_id"],
        "scope": "Disposable server/documents and generated ForgePDM cache cards; original material libraries unchanged",
    }
    (case / "physical-freecad-report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))
finally:
    if observer:
        observer.timer.stop()
        App.removeDocumentObserver(observer)
    for document in reversed(owned):
        if document.Name in App.listDocuments():
            App.closeDocument(document.Name)
    for name, (module, attribute) in previous.items():
        if module is None:
            sys.modules.pop("freecad.forgepdm." + name, None)
        else:
            sys.modules["freecad.forgepdm." + name] = module
        if attribute is None:
            if hasattr(package, name):
                delattr(package, name)
        else:
            setattr(package, name, attribute)
    old_commands.Session.set_client(*old_session)
    if old_active and old_active in App.listDocuments():
        App.setActiveDocument(old_active)
    if previous_controller:
        previous_controller.timer.start()
    after = {
        d.Name: (
            d.FileName,
            old_cad.document_modified(d),
            d.isTouched(),
            hashlib.sha256(Path(d.FileName).read_bytes()).hexdigest()
            if d.FileName and Path(d.FileName).is_file()
            else None,
        )
        for d in App.listDocuments().values()
    }
    assert before == after, "user document state changed"
