"""Real Fasteners solid estimates and optional manual registration on isolated data."""

import hashlib
import importlib.util
import json
from decimal import Decimal
from pathlib import Path
import sys
from uuid import uuid4

import FreeCAD as App
import FastenersCmd
import freecad.forgepdm as package
from freecad.forgepdm import cad, tree_status
from freecad.forgepdm.jobs import Context
from freecad.forgepdm.session import Session

repo = Path("/home/ricardoblank/Development/ForgePDM")
case = Path(globals().get("MASS_FALLBACK_QA_CASE", "/tmp/forgepdm-mass-fallback-qa"))
config = json.loads((case / "connection.json").read_text())
previous = {
    name: (sys.modules.get("freecad.forgepdm." + name), getattr(package, name, None))
    for name in ("ui", "standard_mass")
}
old_session = Session.client, Session.user
old_active = App.ActiveDocument.Name if App.ActiveDocument else None
controller = tree_status._controller
before = {
    d.Name: (
        d.FileName,
        cad.document_modified(d),
        d.isTouched(),
        hashlib.sha256(Path(d.FileName).read_bytes()).hexdigest() if d.FileName else None,
    )
    for d in App.listDocuments().values()
}
owned = []
mode = "estimate"


def load(name, filename):
    spec = importlib.util.spec_from_file_location(
        "freecad.forgepdm." + name, repo / "clients/freecad/freecad/forgepdm" / filename
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def drive(action):
    try:
        request = next(action)
    except StopIteration as done:
        return done.value
    while True:
        try:
            value = request.execute(Context())
        except Exception as error:
            try:
                request = action.throw(error)
            except StopIteration as done:
                return done.value
        else:
            try:
                request = action.send(value)
            except StopIteration as done:
                return done.value


def choose():
    for dialog in ui.QtWidgets.QApplication.topLevelWidgets():
        if (
            isinstance(dialog, ui.QtWidgets.QDialog)
            and dialog.isVisible()
            and dialog.windowTitle() == "Register Standard Fastener"
        ):
            if mode == "estimate":
                for name, value in [
                    ("material", "carbon"),
                    ("grade", "8.8"),
                    ("finish", "zinc plated"),
                ]:
                    combo = dialog.findChild(ui.QtWidgets.QComboBox, "standard_" + name)
                    index = next(
                        i
                        for i in range(combo.count())
                        if combo.itemData(i) == value
                        or combo.itemText(i).casefold().endswith(value)
                    )
                    combo.setCurrentIndex(index)
            if mode == "manual":
                dialog.findChild(ui.QtWidgets.QCheckBox, "standard_manual_mass").setChecked(True)
                dialog.findChild(ui.QtWidgets.QLineEdit, "standard_manual_mass_g").setText("12.5")
                dialog.findChild(ui.QtWidgets.QLineEdit, "standard_manual_mass_note").setText(
                    "Measured QA sample"
                )
            dialog.accept()
            return
    ui.QtCore.QTimer.singleShot(50, choose)


try:
    if controller:
        controller.timer.stop()
    ui = load("ui", "ui.py")
    package.ui = ui
    standard_mass = load("standard_mass", "standard_mass.py")
    package.standard_mass = standard_mass
    api = load("_fallback_api_fixture", "api.py")
    commands = load("_fallback_commands_fixture", "commands.py")
    client = api.ForgePDMClient(config["url"])
    user = client.login("web-admin", config["password"])
    Session.set_client(client, user)
    doc = App.newDocument("MassFallback" + uuid4().hex[:8])
    owned.append(doc)
    checks = []
    items = {}
    for label, diameter, length in [
        ("estimate", "M8", "50"),
        ("unknown", "M10", "60"),
        ("manual", "M12", "70"),
    ]:
        mode = label
        obj = doc.addObject("Part::FeaturePython", "Fastener")
        FastenersCmd.FSScrewObject(obj, "ISO4016", None)
        obj.Diameter = diameter
        doc.recompute()
        lengths = obj.getEnumerationsOfProperty("Length")
        if length in lengths:
            obj.Length = length
        else:
            obj.Length = next(v for v in lengths if v.casefold() == "custom")
            obj.LengthCustom = float(length)
        obj.Thread = False
        doc.recompute()
        assert obj.Shape.isValid() and obj.Shape.Volume > 0
        original_hash = hashlib.sha256(obj.Shape.exportBrepToString().encode()).hexdigest()
        ui.QtCore.QTimer.singleShot(50, choose)
        item = drive(
            commands._register_standard(
                client, {"geometry": standard_mass.fasteners.extract(obj)}, mass_object=obj
            )
        )
        mass = client.get_reference_mass(item["current_revision_id"])
        items[label] = item
        if label == "estimate":
            assert mass["status"] == "cad_estimate" and mass["thread_mode"] == "simplified"
            expected = Decimal(str(obj.Shape.Volume)) * Decimal("7800") / Decimal("1e9")
            assert abs(Decimal(mass["mass_kg"]) - expected) < Decimal("1e-12")
            assert mass["shape_sha256"] == original_hash
            checks.append(
                "real controlled registration automatically estimates a real ISO4016 solid using selected carbon-steel reference density"
            )
        elif label == "unknown":
            assert mass["mass_kg"] is None and mass["estimate_context"] is None
            checks.append("unknown selected material remains unavailable and registration succeeds")
        else:
            assert (
                mass["status"] == "manual"
                and mass["mass_kg"] == "0.0125"
                and mass["note"] == "Measured QA sample"
            )
            client.checkin(item["current_revision_id"])
            client.transition(item["current_revision_id"], "released")
            assert client.lookup_reference_mass(item["current_revision_id"]) == mass
            checks.append(
                "optional native manual grams entry persists and is reused on the Released S revision"
            )
        assert hashlib.sha256(obj.Shape.exportBrepToString().encode()).hexdigest() == original_hash
    report = {
        "runtime": App.Version()[:3],
        "checks": checks,
        "items": items,
        "scope": "Disposable server and native objects; existing user documents preserved",
    }
    (case / "mass-fallback-freecad-report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({"checks": checks}))
finally:
    for doc in reversed(owned):
        if doc.Name in App.listDocuments():
            App.closeDocument(doc.Name)
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
    Session.set_client(*old_session)
    if old_active and old_active in App.listDocuments():
        App.setActiveDocument(old_active)
    if controller:
        controller.timer.start()
    after = {
        d.Name: (
            d.FileName,
            cad.document_modified(d),
            d.isTouched(),
            hashlib.sha256(Path(d.FileName).read_bytes()).hexdigest() if d.FileName else None,
        )
        for d in App.listDocuments().values()
    }
    assert before == after, "user document state changed"
