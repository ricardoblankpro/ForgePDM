"""Run in disposable FreeCAD documents after starting standard_parts_server.py."""
# ruff: noqa: E402 -- isolate the server / select repository code before imports.

import json
import sys
from pathlib import Path

_repo = Path(json.loads(Path("/tmp/forgepdm-standard-live-config.json").read_text())["repository"])
sys.path.insert(0, str(_repo / "clients/freecad"))
import freecad

freecad.__path__.insert(0, str(_repo / "clients/freecad/freecad"))
import freecad.forgepdm

freecad.forgepdm.__path__.insert(0, str(_repo / "clients/freecad/freecad/forgepdm"))
import importlib

from freecad.forgepdm import api, bom, cad, commands, fasteners, fcstd, part_checkin, workspace
from freecad.forgepdm.jobs import Context

for module in (fasteners, fcstd, workspace, api, cad, bom, part_checkin, commands):
    importlib.reload(module)
import FastenersCmd
import FreeCAD as App
import FreeCADGui as Gui
import Part

for name in [
    "ForgePDM_LiveStandardAssembly",
    "ForgePDM_LiveStandardPlate",
    "ForgePDM_LiveStandardBearing",
]:
    if name in App.listDocuments():
        App.closeDocument(name)
config = json.loads(Path("/tmp/forgepdm-standard-live-config.json").read_text())
checks = []


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    checks.append(label)


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


_previous_session = (commands.Session.client, commands.Session.user)
try:
    client = api.ForgePDMClient(config["url"])
    login = client.login("pilot", "isolated-test-password")
    commands.Session.client = client
    commands.Session.user = dict(id=config["user"], role="admin")
    root = Path(config["root"]) / "workspace"
    root.mkdir(exist_ok=True)
    part = client.create_item("part", "Pilot plate", config["project"])
    plate = App.newDocument("ForgePDM_LiveStandardPlate")
    shape = plate.addObject("PartDesign::Feature", "Plate")
    shape.Shape = Part.makeBox(30, 30, 4).cut(Part.makeCylinder(4, 4, App.Vector(15, 15, 0)))
    commands._set_metadata(
        plate,
        ItemId=part["id"],
        RevisionId=part["current_revision_id"],
        ItemNumber=part["number"],
        RevisionLabel="A",
        ServerUrl=client.base_url,
    )
    plate.recompute()
    plate.saveAs(client.prepare_working(str(root)))
    Gui.getDocument(plate.Name).save()
    client.upload_native(plate.FileName, part["current_revision_id"], part["id"], [])
    check("Managed plate uploaded", True)
    parent = client.create_item("assembly", "Fasteners pilot", config["project"])
    doc = App.newDocument("ForgePDM_LiveStandardAssembly")
    assembly = doc.addObject("Assembly::AssemblyObject", "Assembly")
    commands._set_metadata(
        doc,
        ItemId=parent["id"],
        RevisionId=parent["current_revision_id"],
        ItemNumber=parent["number"],
        RevisionLabel="A",
        ServerUrl=client.base_url,
    )
    doc.saveAs(client.prepare_working(str(root)))
    link = doc.addObject("App::Link", "PlateLink")
    link.setLink(shape)
    assembly.addObject(link)
    edge = next(
        (
            "Edge" + str(i + 1)
            for i, e in enumerate(shape.Shape.Edges)
            if hasattr(e.Curve, "Radius")
        ),
        None,
    )
    check("Circular attachment edge found", bool(edge))
    for standard, count in [("ISO4017", 8), ("ISO4032", 2), ("ISO7089", 2), ("ISO4762", 1)]:
        for index in range(count):
            obj = doc.addObject("Part::FeaturePython", "Fastener")
            FastenersCmd.FSScrewObject(obj, standard, None)
            if not (standard == "ISO4017" and index == 7):
                assembly.addObject(obj)
            obj.BaseObject = (shape if index == 0 else link, [edge])
    doc.recompute()
    Gui.getDocument(doc.Name).save()
    App.setActiveDocument(doc.Name)
    originals = {
        key: getattr(commands, key)
        for key in ["ask_choice", "ask_text", "_select_record", "information"]
    }

    def select(*args, **kwargs):
        if False:
            yield
        return {"id": config["project"]}

    def choose(title, prompt, choices, default=None):
        return choices[0] if choices[0] != "Register a new S item" else "Register a new S item"

    def text(title, prompt, default="", **kwargs):
        if prompt.startswith("Material"):
            return "steel"
        if prompt.startswith("Grade"):
            return "8.8"
        if prompt.startswith("Finish"):
            return "zinc"
        return default or "Pilot component"

    from freecad.forgepdm import standard_options, ui

    original_specification_dialog = ui.standard_specification_dialog

    def specification_dialog(geometry):
        kind, family = standard_options.classification(geometry)
        grade_id = (
            "ISO 898-2:8"
            if kind == "NUT"
            else "ISO 898-3:200HV"
            if kind == "WASHER"
            else "ISO 898-1:8.8"
        )
        spec = standard_options.selected_spec(geometry, "steel", grade_id, "zinc", kind, family)
        name, description = standard_options.catalog_text(spec, kind, family)
        return dict(specification=spec, name=name, description=description)

    ui.standard_specification_dialog = specification_dialog
    commands._select_record = select
    commands.ask_choice = choose
    commands.ask_text = text
    commands.information = lambda *args: None
    try:
        check(
            "Upload preflight registers and associates",
            drive(commands._associate_fasteners(client, doc)) is True,
        )
        check("All occurrences associated", len(fasteners.capture(doc)) == 13)
        check(
            "Document-root fastener participates in preflight",
            any(o not in assembly.Group for o in fasteners.objects(doc)),
        )
        check(
            "Four families registered",
            len(
                {
                    row["id"]
                    for obj in fasteners.objects(doc)
                    for row in client.standard_matches(fasteners.extract(obj))["items"]
                }
            )
            == 4,
        )
        check(
            "Unchanged preflight reuses associations",
            drive(commands._associate_fasteners(client, doc)) is True,
        )
    finally:
        ui.standard_specification_dialog = original_specification_dialog
        for key, value in originals.items():
            setattr(commands, key, value)
    bearing_item = client.create_item(
        "part", "Purchased bearing pilot", config["project"], number_series="S"
    )
    bearing = App.newDocument("ForgePDM_LiveStandardBearing")
    body = bearing.addObject("PartDesign::Feature", "Bearing")
    body.Shape = Part.makeCylinder(10, 5).cut(Part.makeCylinder(5, 5))
    commands._set_metadata(
        bearing,
        ItemId=bearing_item["id"],
        RevisionId=bearing_item["current_revision_id"],
        ItemNumber=bearing_item["number"],
        RevisionLabel="A",
        ServerUrl=client.base_url,
    )
    bearing.recompute()
    bearing.saveAs(client.prepare_working(str(root)))
    Gui.getDocument(bearing.Name).save()
    client.upload_native(
        bearing.FileName, bearing_item["current_revision_id"], bearing_item["id"], []
    )
    for index in range(2):
        occurrence = doc.addObject("App::Link", "BearingLink")
        occurrence.setLink(body)
        assembly.addObject(occurrence)
        occurrence.Placement.Base = App.Vector(index * 30, 0, 0)
    App.setActiveDocument(doc.Name)
    check("Purchased S model inserted twice", True)
    doc.recompute()
    Gui.getDocument(doc.Name).save()
    references = cad.capture(doc)
    check(
        "Direct attachments captured",
        len([r for r in references if r["property_name"] == "BaseObject"]) == 4,
    )
    client.upload_native(doc.FileName, parent["current_revision_id"], parent["id"], references)
    check("Upload with external attachments succeeds", True)
    captured = cad.capture_bom(doc)
    prepared = client.prepare_cad_bom(doc.FileName, parent["current_revision_id"], captured)
    proposal = bom.propose_lines(
        {"profile": "freecad-app-link-v1", "references": prepared["references"]},
        [(r["object_name"], r["property_name"]) for r in prepared["references"]],
    )
    check("Mixed BOM quantities", sorted(line.quantity for line in proposal) == [1, 1, 2, 2, 2, 8])
    snapshot = client.bom_snapshot(parent["current_revision_id"])
    client.synchronize_cad_bom(
        doc.FileName,
        parent["current_revision_id"],
        captured,
        prepared["source_hash"],
        [line.as_payload() for line in proposal],
        snapshot,
    )
    check("Reviewed BOM synchronized", len(client.get_bom(parent["current_revision_id"])) == 6)
    result = client.checkin_part(
        doc.FileName, parent["current_revision_id"], parent["id"], config["user"], references
    )
    check("Atomic check-in completes", result["status"] == "completed")
    check(
        "Check-in response recovery",
        client.resume_part_checkin(
            doc.FileName, parent["current_revision_id"], parent["id"], config["user"]
        )["status"]
        == "completed",
    )
    record = result["dataset"]["files"][0]
    configuration = client.retrieve_configuration(
        str(root), parent["current_revision_id"], result["dataset"]["id"], record["id"]
    )
    opened = cad.open_configuration(configuration, commands._set_metadata)
    client.finish_configuration(configuration)
    retrieved = opened["root"]
    check("Historical associations reconstructed", len(fasteners.capture(retrieved)) == 13)
    check(
        "Historical BOM quantities retained",
        len(client.get_bom(parent["current_revision_id"])) == 6,
    )
    check("Retrieved document clean", not cad.document_modified(retrieved))
    check(
        "Attachment targets preserved",
        all(fasteners.attachment(o) for o in fasteners.objects(retrieved)),
    )
    report = dict(
        checks=checks,
        freecad=App.Version()[:3],
        families=["ISO4017", "ISO4032", "ISO7089", "ISO4762"],
    )
    Path("/tmp/forgepdm-standard-live-result.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))

finally:
    commands.Session.client, commands.Session.user = _previous_session
