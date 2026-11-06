"""Follow-up live standard-parts fixture; execute in the running FreeCAD GUI."""

import importlib
import json
from pathlib import Path

import FreeCAD as App
import FreeCADGui as Gui

from freecad.forgepdm import api, cad, commands, fasteners

importlib.reload(fasteners)
importlib.reload(cad)
if "ForgePDM_LiveStandardNested" in App.listDocuments():
    App.closeDocument("ForgePDM_LiveStandardNested")
config = json.loads(Path("/tmp/forgepdm-standard-live-config.json").read_text())
report = json.loads(Path("/tmp/forgepdm-standard-live-result.json").read_text())
client = api.ForgePDMClient(config["url"])
client.login("pilot", "isolated-test-password")
doc = App.getDocument("ForgePDM_LiveStandardAssembly")
meta = doc.getObject("ForgePDM_Metadata")
client.upload_native(doc.FileName, meta.RevisionId, meta.ItemId, cad.capture(doc))
parent = client.create_item("assembly", "Nested fastener boundary pilot", config["project"])
nested = App.newDocument("ForgePDM_LiveStandardNested")
assembly = nested.addObject("Assembly::AssemblyObject", "Assembly")
commands._set_metadata(
    nested,
    ItemId=parent["id"],
    RevisionId=parent["current_revision_id"],
    ItemNumber=parent["number"],
    RevisionLabel="A",
    ServerUrl=client.base_url,
)
nested.saveAs(client.prepare_working(str(Path(config["root"]) / "workspace")))
link = nested.addObject("Assembly::AssemblyLink", "Subassembly")
link.LinkedObject = doc.getObject("Assembly")
assembly.addObject(link)
nested.recompute()
Gui.getDocument(nested.Name).save()
occurrences = cad.capture_bom(nested)
assert len(occurrences) == 1 and occurrences[0]["target_revision_id"] == meta.RevisionId
report["checks"].append("Linked subassembly counts once without embedded fastener flattening")
dataset = client.upload_native(
    nested.FileName, parent["current_revision_id"], parent["id"], cad.capture(nested)
)
configuration = client.retrieve_configuration(
    str(Path(config["root"]) / "workspace"),
    parent["current_revision_id"],
    dataset["id"],
    dataset["files"][0]["id"],
)
opened = cad.open_configuration(configuration, commands._set_metadata)
client.finish_configuration(configuration)
assert len(cad.capture_bom(opened["root"])) == 1
report["checks"].append("Nested assembly retrieval preserves direct BOM boundary")
report["checks"].append("Native subassembly containing embedded fasteners uploads")
Path("/tmp/forgepdm-standard-live-result.json").write_text(json.dumps(report, indent=2))
print("Subassembly checks passed")
