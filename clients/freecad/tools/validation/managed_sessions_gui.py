"""Isolated native managed-generation and representation acceptance.

Run only in a separate temporary FreeCAD profile; the caller owns process exit.
Fastener-shaped native fixture objects exercise links without third-party proxies.
"""


def run(App, Gui, directory):
    from pathlib import Path
    from freecad.forgepdm.session import Session

    directory = Path(directory).resolve()
    assert directory.is_relative_to(Path("/tmp"))
    assert Path(App.getUserAppDataDir()).resolve().is_relative_to(Path("/tmp"))
    assert not App.listDocuments() and Session.client is None
    directory.mkdir(parents=True, exist_ok=True)

    import Part
    from freecad.forgepdm import cad, commands, insertion, workspace, managed_session
    from freecad.forgepdm.session import Session

    assert not App.listDocuments() and Session.client is None
    checks = []

    def check(label, value):
        assert value, label
        checks.append(label)

    source = App.newDocument("Source")
    root = source.addObject("Assembly::AssemblyObject", "Assembly")
    solid = source.addObject("Part::Feature", "Core")
    solid.Shape = Part.makeBox(10, 10, 10)
    root.addObject(solid)
    for n in ["Bolt", "Washer"]:
        o = source.addObject("Part::Feature", n)
        o.Shape = Part.makeCylinder(2, 3)
        o.addProperty("App::PropertyBool", "FixtureFastener")
        o.FixtureFastener = True
    insertion.fasteners.objects = lambda d: [
        o for o in d.Objects if o.TypeId == "Part::Feature" and hasattr(o, "FixtureFastener")
    ]
    insertion.fasteners.recognized = lambda o: (
        o.TypeId == "Part::Feature" and hasattr(o, "FixtureFastener")
    )
    insertion.fasteners.capture = lambda d: []
    commands._set_metadata(
        source,
        ItemId="source",
        RevisionId="source-rev",
        ItemNumber="A000003",
        RevisionLabel="A",
        ServerUrl="http://fixture",
    )
    insertion.assign_member_ids(source)
    source.recompute()
    source.saveAs(str(directory / "source.FCStd"))
    source.commitTransaction()
    parent = App.newDocument("Parent")
    parent.addObject("Assembly::AssemblyObject", "Assembly")
    commands._set_metadata(
        parent,
        ItemId="parent",
        RevisionId="parent-rev",
        ItemNumber="A000004",
        RevisionLabel="A",
        ServerUrl="http://fixture",
    )
    parent.recompute()
    parent.saveAs(str(directory / "parent.FCStd"))
    parent.commitTransaction()
    first = insertion.insert(parent, source, "One")
    second = insertion.insert(parent, source, "Two")
    check("v2 complete source identity", insertion.source(first) is root)
    import JointObject

    joints = parent.Assembly.newObject("Assembly::JointGroup", "Joints")
    ground = joints.newObject("App::FeaturePython", "GroundedJoint")
    JointObject.GroundedJoint(ground, first)
    JointObject.ViewProviderGroundedJoint(ground.ViewObject)
    joint = joints.newObject("App::FeaturePython", "FixedJoint")
    JointObject.Joint(joint, 0)
    JointObject.ViewProviderJoint(joint.ViewObject)
    a = first.LinkedObject.Group[1].Name
    b = second.LinkedObject.Group[1].Name
    joint.Proxy.setJointConnectors(
        joint,
        [
            [parent.Assembly, [first.Name + "." + a + ".Face1", first.Name + "." + a + ".Vertex1"]],
            [
                parent.Assembly,
                [second.Name + "." + b + ".Face1", second.Name + "." + b + ".Vertex1"],
            ],
        ],
    )
    parent.recompute()
    parent.commitTransaction()
    from freecad.forgepdm import replacement

    joint_refs = replacement._joint_references(parent)
    check("native joints resolve through representation members", bool(joint_refs))
    names = [o.Name for o in first.LinkedObject.Group]
    source.removeObject("Washer")
    source.recompute()
    Gui.getDocument(source.Name).save()
    source.commitTransaction()
    try:
        insertion.source(first)
    except workspace.WorkspaceError:
        checks.append("deleted member diagnosed without losing source")
    else:
        raise AssertionError("missing member accepted")
    parent.openTransaction("Reconcile")
    insertion.retarget(first.LinkedObject, source)
    insertion.retarget(second.LinkedObject, source)
    parent.recompute()
    parent.commitTransaction()
    check(
        "deleted member reconciles in two occurrences",
        len(first.LinkedObject.Group) == 2 and len(second.LinkedObject.Group) == 2,
    )
    check("surviving members retain names", [o.Name for o in first.LinkedObject.Group] == names[:2])
    check("BOM retains two subassembly occurrences", len(cad.capture_bom(parent)) == 2)
    parent.recompute()
    parent.saveAs(str(directory / "parent.FCStd"))
    parent.commitTransaction()
    check("parent saved with complete representations", insertion.source(second) is root)
    # Freeze the saved source graph, then edit the original and verify isolation.
    test_root = directory / "workspace"
    working = workspace.prepare_working("http://fixture", test_root)
    workspace.copy_revision_source(source.FileName, working, [])
    value = workspace.binding(working, "http://fixture", False)
    value["entry"].update(
        item_id="source", revision_id="source-rev", item_number="A000003", revision_label="A"
    )
    workspace._atomic_json(value["directory"] / workspace.MANIFEST, value["ledger"])
    saved = App.openDocument(working)
    saved.recompute()
    Gui.getDocument(saved.Name).save()
    saved.commitTransaction()
    graph = cad.capture_graph(saved)
    configuration = managed_session.freeze("http://fixture", graph, working)
    opened = cad.open_configuration(configuration, commands._set_metadata)
    client = type(
        "FixtureClient", (), dict(base_url="http://fixture", _checkpoint=lambda self: None)
    )()
    workspace.finish(client, configuration)
    frozen = opened["root"]
    check(
        "saved local generation opens with complete native geometry",
        len(insertion.source_members(frozen)) == 2,
    )
    frozen_volume = frozen.Bolt.Shape.Volume
    saved.Bolt.Shape = Part.makeCylinder(4, 3)
    saved.recompute()
    check(
        "editable changes do not leak into local generation",
        frozen.Bolt.Shape.Volume == frozen_volume,
    )
    parent.commitTransaction()
    from freecad.forgepdm import replacement

    refs = cad.capture_bom(parent)
    replacement.apply(
        parent,
        refs,
        [first.Name, second.Name],
        frozen,
        dict(id="source-rev", item_id="source"),
        target_generation=configuration["ledger"]["root_file_id"],
    )
    check(
        "saved local generation updates both occurrences without upload",
        insertion.source(first).Document is frozen and insertion.source(second).Document is frozen,
    )
    check(
        "native joints survive deletion and local generation update",
        replacement._joint_references(parent) == joint_refs,
    )
    frozen.Bolt.Shape = Part.makeCylinder(2, 3)
    parent.recompute()
    backup = directory / "unsaved-parent-backup.FCStd"
    prior = (parent.FileName, Gui.getDocument(parent.Name).Modified)
    parent.saveCopy(str(backup))
    check(
        "recovery saveCopy preserves live path and modified state",
        (parent.FileName, Gui.getDocument(parent.Name).Modified) == prior,
    )

    frozen.removeObject("Bolt")
    frozen.recompute()
    parent.commitTransaction()
    references = cad.capture_bom(parent, allow_incomplete=True)
    replacement.apply(
        parent,
        references,
        [first.Name, second.Name],
        source,
        dict(id="source-rev", item_id="source"),
        restoration=True,
    )
    check(
        "cancellation restores a deleted constrained member using recorded identity",
        replacement._joint_references(parent) == joint_refs and len(cad.capture_bom(parent)) == 2,
    )

    return dict(
        checks=checks, freecad=App.Version(), production_mutations=False, server_mutations=False
    )
