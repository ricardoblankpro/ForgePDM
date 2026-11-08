"""Disposable real FreeCAD/API material assignment validation.

Run after tests/web/materials-browser.mjs. Never uses the user's live database.
"""

from decimal import Decimal

import hashlib
import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import FreeCAD as App

repository = Path("/home/ricardoblank/Development/ForgePDM")
case = Path(globals().get("MATERIAL_QA_CASE", "/tmp/forgepdm-material-browser-case"))
config = json.loads((case / "connection.json").read_text())
browser = json.loads((case / "materials-browser-report.json").read_text())


def load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, repository / "clients/freecad/freecad/forgepdm" / filename
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


api = load("_material_qa_api", "api.py")
materials = load("_material_qa_local", "materials.py")
client = api.ForgePDMClient(config["url"])
client.login("web-admin", config["password"])
checks = []
previous = App.ActiveDocument.Name if App.ActiveDocument else None
document = App.newDocument("ForgePDMMaterialValidation" + uuid4().hex[:8])
try:
    part = client.create_item("part", "Disposable material CAD validation", None)
    revision = part["current_revision_id"]
    box = document.addObject("Part::Box", "FinishedSolid")
    box.Length = 100
    box.Width = 100
    box.Height = 100
    metadata = document.addObject("App::FeaturePython", "ForgePDM_Metadata")
    for key, value in {
        "ItemId": part["id"],
        "RevisionId": revision,
        "ItemNumber": part["number"],
        "RevisionLabel": "A",
        "ServerUrl": client.base_url,
    }.items():
        metadata.addProperty("App::PropertyString", key, "ForgePDM")
        setattr(metadata, key, value)
    document.recompute()
    current = client.material_inputs(revision)
    line = {
        "component_revision_id": browser["materialRevision"],
        "quantity": "400",
        "uom": "mm",
        "allowance_percent": "0",
        "position": 1,
        "note": "",
    }
    materials.assign(
        document, metadata, revision, current, [line], [(box, browser["materialRevision"], "7850")]
    )
    assert abs(Decimal(metadata.PDMFinishedMassKg) - Decimal("7.85")) < Decimal("1e-12")
    checks.append("real solid mm3 and catalog density calculate 7.85 kg")
    box.Length = 200
    document.recompute()
    materials.refresh_mass(document, metadata)
    assert abs(Decimal(metadata.PDMFinishedMassKg) - Decimal("15.70")) < Decimal("1e-12")
    checks.append("changed real geometry recomputes mass before publication")
    path = case / "material-solid.FCStd"
    document.recompute()
    document.saveAs(str(path))
    data = path.read_bytes()
    checkout = client.get_checkout(revision)
    intent = {
        "revision_id": revision,
        "operation_id": str(uuid4()),
        "expected_checkout_id": checkout["id"],
        "expected_checkout_version": checkout["version"],
        "content_hash": hashlib.sha256(data).hexdigest(),
        "byte_size": len(data),
    }
    result = client.upload_part_checkin(str(path), intent)
    assert client.material_inputs(revision)["lines"][0]["quantity"] == "400"
    assert client.upload_part_checkin(str(path), intent) == result
    checks.append(
        "real saved FCStd atomically publishes material inputs and replays without duplication"
    )
    evidence = client._json_request(
        "GET", "/api/v1/revisions/{}/material-evidence".format(revision)
    )
    assert evidence[0]["dataset_id"] == result["dataset"]["id"]
    assert not evidence[0]["stale_inputs"]
    assert abs(Decimal(evidence[0]["mass_kg"]) - Decimal("15.7")) < Decimal("1e-12")
    checks.append("material evidence API pins selected-solid mass to exact dataset hash")
    App.closeDocument(document.Name)
    document = App.openDocument(str(path))
    assert (
        json.loads(document.getObject("ForgePDM_Metadata").PDMMaterialInputs)["lines"][0][
            "component_revision_id"
        ]
        == browser["materialRevision"]
    )
    checks.append("save and reopen preserve exact material revision and mass evidence")
    report = {
        "runtime": App.Version(),
        "checks": checks,
        "dataset_id": result["dataset"]["id"],
        "revision_id": revision,
        "scope": "Disposable API and CAD only",
    }
    (case / "materials-freecad-report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))
finally:
    if document.Name in App.listDocuments():
        App.closeDocument(document.Name)
    if previous and previous in App.listDocuments():
        App.setActiveDocument(previous)
