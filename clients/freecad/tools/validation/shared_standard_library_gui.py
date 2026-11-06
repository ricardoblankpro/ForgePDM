"""Run through FreeCAD MCP after starting standard_parts_server.py.

Uses its disposable backend; leaves user documents and authentication untouched.
"""
# ruff: noqa: F821 -- App/Gui are supplied by the FreeCAD MCP execution environment.

import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path

from freecad.forgepdm import api, standard_options, ui
from freecad.forgepdm.jobs import Context
from freecad.forgepdm.session import Session


def state():
    return [
        (
            d.Name,
            Gui.getDocument(d.Name).Modified,
            d.isTouched(),
            [(o.Name, list(o.State)) for o in d.Objects],
            hashlib.sha256(Path(d.FileName).read_bytes()).hexdigest()
            if d.FileName and Path(d.FileName).is_file()
            else None,
        )
        for d in App.listDocuments().values()
    ]


before = state()
session = (Session.client, Session.user)
assert not Session.busy
config = json.loads(Path("/tmp/forgepdm-standard-live-config.json").read_text())
spec = importlib.util.spec_from_file_location(
    "freecad.forgepdm._library_probe",
    Path(config["repository"]) / "clients/freecad/freecad/forgepdm/commands.py",
)
commands = importlib.util.module_from_spec(spec)
spec.loader.exec_module(commands)
checks = []


def check(label, value):
    assert value, label
    checks.append(label)


def unexpected(*args, **kwargs):
    raise AssertionError("Unexpected project or text prompt")


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


client = api.ForgePDMClient(config["url"])
client.login("pilot", "isolated-test-password")
cap = client.standard_capabilities()
lib = cap["library_project_id"]
check(
    "Backend advertises shared library and administrator registration",
    cap["shared_library"] and cap["can_register"],
)
geometry = {"Type": "ISO4016", "Diameter": "M12", "Length": "70"}
selected = standard_options.selected_spec(
    geometry, "carbon", "ISO 898-1:8.8", "zinc", "SCREW", "HEX HEAD"
)
name, description = standard_options.catalog_text(selected, "SCREW", "HEX HEAD")
old = ui.standard_specification_dialog
ui.standard_specification_dialog = lambda _: dict(
    specification=selected, name=name, description=description
)
commands._select_record = unexpected
commands.ask_text = unexpected
try:
    item = drive(commands._register_standard(client, {"geometry": geometry}))
finally:
    ui.standard_specification_dialog = old
check(
    "Real FreeCAD registration completes without project/text prompts",
    item["number"].startswith("S"),
)
check(
    "Shared catalog returns generated specification",
    any(v["id"] == item["id"] for v in client.search_items(number_series="S")["items"]),
)
legacy = client.create_item(
    "part", "Legacy client routed part", config["project"], number_series="S"
)
check("Legacy client S request accepted with consuming project", legacy["number"].startswith("S"))
user = client._json_request(
    "POST",
    "/api/v1/admin/users",
    dict(username="reader", display_name="Library reader", password="isolated-reader-password"),
)
reader = api.ForgePDMClient(config["url"])
reader.login("reader", "isolated-reader-password")
reader._json_request(
    "POST",
    "/api/v1/auth/password",
    dict(current_password="isolated-reader-password", new_password="isolated-reader-password2"),
)
reader.login("reader", "isolated-reader-password2")
check(
    "New engineer gets read-only library capability",
    not reader.standard_capabilities()["can_register"],
)
check("New engineer can read shared S item", reader.get_item(item["id"])["id"] == item["id"])
try:
    reader.create_item("part", "Forbidden", number_series="S")
    raise AssertionError("reader created standard part")
except api.ForgePDMError as error:
    check("Server denies reader registration", error.status == 403)
try:
    drive(commands._register_standard(reader, {"geometry": geometry}))
    raise AssertionError("reader passed UI gate")
except commands.workspace.WorkspaceError:
    checks.append("FreeCAD rejects read-only registration before prompting")
client._json_request(
    "PUT", f"/api/v1/management/projects/{lib}/members/{user['id']}", dict(role="editor")
)
check(
    "Administrator can grant library maintainer access",
    reader.standard_capabilities()["can_register"],
)
reader.create_item("part", "Curator registered part", number_series="S")
checks.append("Library editor registers without engineering-project membership")
p2 = client._json_request(
    "POST",
    "/api/v1/management/projects",
    dict(project_number="TEST-OTHER", name="Other consuming project"),
)
for project in [config["project"], p2["id"]]:
    assembly = client.create_item("assembly", "Consumer", project)
    client._json_request(
        "PUT",
        f"/api/v1/revisions/{assembly['current_revision_id']}/bom",
        dict(
            lines=[dict(component_revision_id=item["current_revision_id"], quantity=2, position=1)]
        ),
    )
    check(
        "Exact S revision reusable in project BOM",
        client.get_bom(assembly["current_revision_id"])[0]["component_revision_id"]
        == item["current_revision_id"],
    )

with sqlite3.connect(Path(config["root"]) / "db.sqlite3") as db:
    check(
        "All S items owned only by library",
        not db.execute(
            "SELECT 1 FROM project_items pi JOIN items i ON i.id=pi.item_id WHERE i.number_series='S' AND pi.project_id<>?",
            (lib,),
        ).fetchone(),
    )
    check(
        "Legacy request ownership routed to shared library",
        db.execute(
            "SELECT project_id FROM project_items WHERE item_id=?", (legacy["id"],)
        ).fetchone()[0]
        == lib,
    )
check("User document flags/object states/file hashes preserved", state() == before)
check("User session preserved", session == (Session.client, Session.user))
Path(config["repository"], "docs/validation/shared-standard-library-2026-11-05.json").write_text(
    json.dumps(
        dict(checks=checks, result="passed", data="disposable backend only; no user CAD changes"),
        indent=2,
    )
    + "\n"
)
print(json.dumps(dict(result="passed", checks=checks)))
