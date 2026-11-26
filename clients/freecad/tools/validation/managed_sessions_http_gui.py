"""Disposable native/HTTP managed-session acceptance; no production login.

The external driver supplies a fresh backend fixture, login and evidence list,
executes yielded requests through WorkflowJob, and owns the isolated process exit.
Synthetic native fastener-shaped members isolate the managed graph contract;
real Fasteners geometry is covered separately by copied-document acceptance.
"""


def workflow(App, Gui, client, fixture, directory, username, password, checks):
    from pathlib import Path
    from urllib.parse import urlsplit
    import json
    import Part
    from freecad.forgepdm import commands, cad, insertion, workspace, thumbnail_render
    from freecad.forgepdm.session import Session
    from freecad.forgepdm.jobs import Request

    directory = Path(directory).resolve()
    assert directory.is_relative_to(Path("/tmp"))
    assert Path(App.getUserAppDataDir()).resolve().is_relative_to(Path("/tmp"))
    assert not App.listDocuments() and Session.client is None and client.token is None
    address = urlsplit(client.base_url)
    assert address.hostname in ("127.0.0.1", "localhost") and address.port not in (None, 8000)

    commands.ask_choice = lambda title, prompt, choices, *a: choices[0]
    commands.select_replacement_occurrences = lambda rows, selected: [
        r["object_name"] for r in rows
    ]
    commands.information = lambda *a: None
    commands.warning = lambda *a: None
    thumbnail_render.optional = lambda d: None
    insertion.fasteners.objects = lambda d: [
        o for o in d.Objects if o.TypeId == "Part::Feature" and hasattr(o, "FixtureFastener")
    ]
    insertion.fasteners.recognized = lambda o: (
        o.TypeId == "Part::Feature" and hasattr(o, "FixtureFastener")
    )
    insertion.fasteners.capture = lambda d: []

    def check(label, value):
        assert value, label
        checks.append(label)

    user = yield Request("Login fixture", client.login, (username, password))
    Session.set_client(client, user)
    workroot = str(directory / "workspace")
    source = App.newDocument("HttpSource")
    source.addObject("Assembly::AssemblyObject", "Assembly")
    core = source.addObject("Part::Feature", "Core")
    core.Shape = Part.makeBox(10, 10, 10)
    source.Assembly.addObject(core)
    for name in ["Bolt", "Washer"]:
        o = source.addObject("Part::Feature", name)
        o.Shape = Part.makeCylinder(2, 3)
        o.addProperty("App::PropertyBool", "FixtureFastener")
        o.FixtureFastener = True
    meta = fixture["source"]
    commands._set_metadata(
        source,
        ItemId=meta["item_id"],
        RevisionId=meta["revision_id"],
        ItemNumber=meta["item_number"],
        RevisionLabel="A",
        ServerUrl=client.base_url,
    )
    path = yield Request("Source working", client.prepare_working, (workroot,))
    commands._save_managed_as(source, path)
    App.setActiveDocument(source.Name)
    yield from commands.UploadAssemblyGraphCommand().action()
    value = workspace.binding(source.FileName, client.base_url)
    plan = json.loads((value["directory"] / "graph-publication.json").read_text())
    snapshot_path = plan["steps"][source.FileName]["published_path"]
    snapshot = next(d for d in App.listDocuments().values() if d.FileName == snapshot_path)
    check(
        "HTTP atomic source upload retains checkout",
        bool((yield Request("Source lease", client.get_checkout, (meta["revision_id"],)))),
    )
    parent = App.newDocument("HttpParent")
    parent.addObject("Assembly::AssemblyObject", "Assembly")
    data = fixture["parent"]
    commands._set_metadata(
        parent,
        ItemId=data["item_id"],
        RevisionId=data["revision_id"],
        ItemNumber=data["item_number"],
        RevisionLabel="A",
        ServerUrl=client.base_url,
    )
    path = yield Request("Parent working", client.prepare_working, (workroot,))
    commands._save_managed_as(parent, path)
    first = insertion.insert(parent, snapshot, "First")
    second = insertion.insert(parent, snapshot, "Second")
    parent.commitTransaction()
    Gui.getDocument(parent.Name).save()
    original_count = len(first.LinkedObject.Group)
    source.removeObject("Washer")
    source.recompute()
    Gui.getDocument(source.Name).save()
    source.commitTransaction()
    check(
        "editing original leaves uploaded parent occurrence stable",
        len(first.LinkedObject.Group) == original_count,
    )
    App.setActiveDocument(parent.Name)
    yield from commands.UpdateSavedComponentsCommand().action()
    check(
        "saved local deletion updates both occurrences without upload",
        len(first.LinkedObject.Group) == 2 and len(second.LinkedObject.Group) == 2,
    )
    App.setActiveDocument(source.Name)
    yield from commands.CancelCheckoutCommand().action()
    check(
        "cancel restores unpublished parent occurrences before releasing child",
        len(first.LinkedObject.Group) == 3 and len(second.LinkedObject.Group) == 3,
    )
    yield from commands.CheckoutCommand().action()
    source = App.ActiveDocument
    source.removeObject("Washer")
    source.recompute()
    Gui.getDocument(source.Name).save()
    source.commitTransaction()
    check("checkout isolates edits from restored parent", len(first.LinkedObject.Group) == 3)
    App.setActiveDocument(parent.Name)
    yield from commands.UpdateSavedComponentsCommand().action()
    check(
        "local synchronization works after cancellation and new checkout",
        len(first.LinkedObject.Group) == 2,
    )
    yield from commands.CheckInAssemblyGraphCommand().action()
    check(
        "child-first graph checkin releases child checkout",
        (yield Request("Source checked in", client.get_checkout, (meta["revision_id"],))) is None,
    )
    check(
        "child-first graph checkin releases parent checkout",
        (yield Request("Parent checked in", client.get_checkout, (data["revision_id"],))) is None,
    )
    value = workspace.binding(parent.FileName, client.base_url)
    config = yield Request(
        "Reopen published parent",
        client.retrieve_configuration,
        (workroot, data["revision_id"], value["entry"]["dataset_id"], value["entry"]["file_id"]),
    )
    opened = cad.open_configuration(config, commands._set_metadata)
    yield Request("Finish reopened parent", client.finish_configuration, (config,))
    check(
        "HTTP retrieval reconstructs two exact updated occurrences",
        len(cad.capture_bom(opened["root"])) == 2
        and len(insertion.representation(opened["root"].Component).Group) == 2,
    )
    yield Request("New source checkout", client.acquire_checkout, (meta["revision_id"],))
    App.setActiveDocument(source.Name)
    source.removeObject("Bolt")
    source.recompute()
    Gui.getDocument(source.Name).save()
    source.commitTransaction()
    yield from commands.CancelCheckoutCommand().action()
    check(
        "cancel leaves published parent intact without parent checkout",
        len(cad.capture_bom(opened["root"])) == 2,
    )
    check(
        "cancel releases the reviewed new source checkout",
        (yield Request("Cancelled source", client.get_checkout, (meta["revision_id"],))) is None,
    )
    check(
        "cancel restores source read-only snapshot",
        App.ActiveDocument.getObject("Bolt") is not None
        and App.ActiveDocument.getObject("Washer") is None,
    )
