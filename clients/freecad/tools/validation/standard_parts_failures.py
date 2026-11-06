"""Follow-up live standard-parts fixture; execute in the running FreeCAD GUI."""

import importlib
import json
from pathlib import Path

import FreeCAD as App
import FreeCADGui as Gui

from freecad.forgepdm import api, cad, commands, fasteners, workspace
from freecad.forgepdm.jobs import Context

for module in (fasteners, cad, commands):
    importlib.reload(module)
config = json.loads(Path("/tmp/forgepdm-standard-live-config.json").read_text())
report = json.loads(Path("/tmp/forgepdm-standard-live-result.json").read_text())
checks = report["checks"]


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)


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
    client.login("pilot", "isolated-test-password")
    commands.Session.client = client
    commands.Session.user = {"id": config["user"], "role": "admin"}
    doc = App.getDocument("ForgePDM_LiveStandardAssembly")
    App.setActiveDocument(doc.Name)
    meta = doc.getObject("ForgePDM_Metadata")
    client.acquire_checkout(meta.RevisionId)
    bolt = next(o for o in fasteners.objects(doc) if str(o.Type) == "ISO4017")
    original = bolt.Length
    bolt.Length = "30"
    doc.recompute()
    check("Size edit invalidates association", fasteners.association(bolt) is None)
    choices = commands.ask_choice
    commands.ask_choice = lambda *args, **kwargs: None
    try:
        check(
            "Canceled association stops preflight",
            drive(commands._associate_fasteners(client, doc)) is False,
        )
    finally:
        commands.ask_choice = choices
    Gui.getDocument(doc.Name).save()
    before = client.get_bom(meta.RevisionId)
    try:
        client.upload_native(doc.FileName, meta.RevisionId, meta.ItemId, cad.capture(doc))
    except api.ForgePDMError as error:
        check("Backend rejects stale geometry evidence", error.status == 409)
    else:
        raise AssertionError("Stale geometry accepted")
    check("Failed upload preserves engineering BOM", client.get_bom(meta.RevisionId) == before)
    bolt.Length = original
    doc.recompute()
    copy = doc.copyObject(bolt, False)
    doc.getObject("Assembly").addObject(copy)
    doc.recompute()
    old = fasteners.association(bolt)
    check(
        "Copied fastener initially shares UUID",
        fasteners.association(copy)["occurrence_id"] == old["occurrence_id"],
    )
    check(
        "Preflight repairs copied UUID", drive(commands._associate_fasteners(client, doc)) is True
    )
    check(
        "Copied UUID now unique",
        fasteners.association(copy)["occurrence_id"] != old["occurrence_id"],
    )
    doc.removeObject(copy.Name)
    doc.recompute()
    check("Deletion restores original count", len(fasteners.capture(doc)) == 13)
    proxy = bolt.Proxy
    bolt.Proxy = None
    try:
        try:
            fasteners.capture(doc)
        except workspace.WorkspaceError:
            check("Missing proxy fails safely", True)
        else:
            raise AssertionError("Missing proxy accepted")
    finally:
        bolt.Proxy = proxy
    target, edge = fasteners.attachment(bolt)
    bolt.BaseObject = (target, ["Edge999999"])
    try:
        try:
            fasteners.attachment(bolt)
        except workspace.WorkspaceError:
            check("Missing attachment subelement rejected", True)
        else:
            raise AssertionError("Invalid attachment accepted")
    finally:
        bolt.BaseObject = (target, [edge])
        doc.recompute()
    Gui.getDocument(doc.Name).save()
    client.upload_native(doc.FileName, meta.RevisionId, meta.ItemId, cad.capture(doc))
    captured = cad.capture_bom(doc)
    prepared = client.prepare_cad_bom(doc.FileName, meta.RevisionId, captured)
    snapshot = client.bom_snapshot(meta.RevisionId)
    bolt.Offset = 3
    doc.recompute()
    Gui.getDocument(doc.Name).save()
    try:
        client.synchronize_cad_bom(
            doc.FileName, meta.RevisionId, captured, prepared["source_hash"], before, snapshot
        )
    except workspace.WorkspaceError:
        check("Saved edit invalidates BOM review", True)
    else:
        raise AssertionError("Stale review accepted")
    bolt.Offset = 0
    doc.recompute()
    Gui.getDocument(doc.Name).save()
    report["fasteners_version"] = "0.5.43"
    Path("/tmp/forgepdm-standard-live-result.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))

finally:
    commands.Session.client, commands.Session.user = _previous_session
