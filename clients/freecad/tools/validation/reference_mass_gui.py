"""Disposable real FreeCAD registration and live Fabory reference acceptance."""

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import FreeCAD as App

from freecad.forgepdm import cad
from freecad.forgepdm import ui
from freecad.forgepdm.jobs import Context
from freecad.forgepdm.session import Session

repo = Path("/home/ricardoblank/Development/ForgePDM")
case = Path("/tmp/forgepdm-reference-mass-qa")
config = json.loads((case / "connection.json").read_text())
old_client, old_user = Session.client, Session.user
before = {
    d.Name: (
        d.FileName,
        cad.document_modified(d),
        d.isTouched(),
        hashlib.sha256(Path(d.FileName).read_bytes()).hexdigest(),
    )
    for d in App.listDocuments().values()
}


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
            for name, value in [("material", "steel"), ("grade", "10.9"), ("finish", "plain")]:
                combo = dialog.findChild(ui.QtWidgets.QComboBox, "standard_" + name)
                index = next(
                    i
                    for i in range(combo.count())
                    if combo.itemData(i) == value or combo.itemText(i).endswith(value)
                )
                combo.setCurrentIndex(index)
            dialog.accept()
            return
    ui.QtCore.QTimer.singleShot(50, choose)


try:
    api = load("_reference_api_fixture", "api.py")
    commands = load("_reference_commands_fixture", "commands.py")
    client = api.ForgePDMClient(config["url"])
    user = client.login("web-admin", config["password"])
    Session.set_client(client, user)
    ui.QtCore.QTimer.singleShot(50, choose)
    item = drive(
        commands._register_standard(
            client,
            {
                "geometry": {
                    "Type": "ISO4762",
                    "Diameter": "M8",
                    "Length": "30",
                    "LeftHanded": "false",
                }
            },
        )
    )
    assert item["reference_mass"]["mass_kg"] == "0.016", item.get("reference_mass")
    saved = client.get_reference_mass(item["current_revision_id"])
    assert saved == client.lookup_reference_mass(item["current_revision_id"])
    client.checkin(item["current_revision_id"])
    client.transition(item["current_revision_id"], "released")
    assert client.lookup_reference_mass(item["current_revision_id"]) == saved
    report = {
        "runtime": App.Version()[:3],
        "item": item,
        "checks": [
            "real controlled Fasteners registration dialog automatically retrieves verified 16 g supplier mass",
            "repeat association lookup reuses saved reference",
            "Released S revision reuses reference without modification",
        ],
    }
    (case / "reference-freecad-report.json").write_text(json.dumps(report, indent=2))
    print(
        json.dumps(
            {"checks": report["checks"], "number": item["number"], "mass_kg": saved["mass_kg"]}
        )
    )
finally:
    Session.set_client(old_client, old_user)
    after = {
        d.Name: (
            d.FileName,
            cad.document_modified(d),
            d.isTouched(),
            hashlib.sha256(Path(d.FileName).read_bytes()).hexdigest(),
        )
        for d in App.listDocuments().values()
    }
    assert before == after, "user document state changed"
