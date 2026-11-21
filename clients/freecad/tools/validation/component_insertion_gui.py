"""Isolated native insertion acceptance on a copied configuration, without login."""


def run(App, Gui, configuration, directory):
    import hashlib
    from pathlib import Path

    from freecad.forgepdm import cad, commands, insertion, balloon_geometry
    from freecad.forgepdm.session import Session

    assert not App.listDocuments() and Session.client is None
    assert Path(App.getUserAppDataDir()).resolve().is_relative_to(Path("/tmp"))
    assert Path(configuration["directory"]).resolve().is_relative_to(Path("/tmp"))
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    files = [
        Path(configuration["directory"]) / e["path"] for e in configuration["ledger"]["documents"]
    ]
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    source = cad.open_configuration(configuration, commands._set_metadata)["root"]
    # The verified loader rewrites owned configuration paths before insertion.
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    source_members = insertion.source_members(source)
    assert len(source_members) == 4, "Fixture must include three root fasteners"
    checks = []

    def check(label, result):
        assert result, label
        checks.append(label)

    parent = App.newDocument("InsertionParent")
    parent.addObject("Assembly::AssemblyObject", "Assembly")
    commands._set_metadata(
        parent,
        ItemId="parent",
        RevisionId="parent-revision",
        ItemNumber="A-TEST",
        RevisionLabel="A",
        ServerUrl="http://127.0.0.1:8000",
    )
    parent.saveAs(str(directory / "parent.FCStd"))
    parent.commitTransaction()
    first = insertion.insert(parent, source, "Subassembly")
    check(
        "Complete native shape includes external fasteners",
        len(first.Shape.Solids) == sum(len(o.Shape.Solids) for o in source_members),
    )
    check(
        "Member placements match the original assembly and fasteners",
        all(
            link.Placement == original.Placement
            for link, original in zip(insertion.representation(first).Group, source_members)
        ),
    )
    check("Representation resolves source identity", insertion.source(first) is source_members[0])
    check(
        "Balloon identity resolves subassembly revision",
        balloon_geometry.revision(first) == source.ForgePDM_Metadata.RevisionId,
    )
    check("Direct BOM counts one assembly", len(cad.capture_bom(parent)) == 1)
    first_name = first.Name
    parent.undo()
    check("Undo removes occurrence and representation", parent.getObject(first_name) is None)
    parent.redo()
    first = parent.getObject("Component")
    second = insertion.insert(parent, source, "Subassembly")
    check("Repeated occurrences count twice without flattening", len(cad.capture_bom(parent)) == 2)
    check("Occurrences own distinct representations", first.LinkedObject is not second.LinkedObject)
    volume = first.Shape.Volume
    first.Placement.Base = App.Vector(100, 20, 30)
    parent.recompute()
    check(
        "Rigid movement retains complete geometry",
        abs(first.Shape.Volume - volume) < 1e-7 and first.Shape.BoundBox.XMin > 20,
    )
    import JointObject

    joints = parent.Assembly.newObject("Assembly::JointGroup", "Joints")
    ground = joints.newObject("App::FeaturePython", "GroundedJoint")
    JointObject.GroundedJoint(ground, first)
    JointObject.ViewProviderGroundedJoint(ground.ViewObject)
    joint = joints.newObject("App::FeaturePython", "FixedJoint")
    JointObject.Joint(joint, 0)
    JointObject.ViewProviderJoint(joint.ViewObject)
    member1 = insertion.representation(first).Group[1].Name
    member2 = insertion.representation(second).Group[1].Name
    joint.Proxy.setJointConnectors(
        joint,
        [
            [
                parent.Assembly,
                [first.Name + "." + member1 + ".Face1", first.Name + "." + member1 + ".Vertex1"],
            ],
            [
                parent.Assembly,
                [second.Name + "." + member2 + ".Face1", second.Name + "." + member2 + ".Vertex1"],
            ],
        ],
    )
    parent.recompute()
    check(
        "Native grounded and fixed joints accept inserted occurrences",
        ground.ObjectToGround is first
        and joint.Reference1 is not None
        and joint.Reference2 is not None,
    )
    page = parent.addObject("TechDraw::DrawPage", "Page")
    template = parent.addObject("TechDraw::DrawSVGTemplate", "Template")
    template.Template = source.Page.Template.Template
    page.Template = template
    view = parent.addObject("TechDraw::DrawViewPart", "View")
    view.Source = [first, second]
    page.addView(view)
    view.X, view.Y, view.Scale = 160, 140, 0.6
    view.Direction = App.Vector(1, -1, 1)
    page.ViewObject.show()
    Gui.updateGui()
    parent.recompute()
    cad.settle_techdraw(parent)
    import TechDrawGui

    TechDrawGui.exportPageAsPdf(page, str(directory / "insertion.pdf"))
    check(
        "Native PDF exports the complete linked representation",
        (directory / "insertion.pdf").stat().st_size > 1000,
    )
    refs = cad.capture(parent)
    check("Whole-object references retain all source members", len(refs) == 8)
    import json

    (directory / "geometry.json").write_text(
        json.dumps(
            {
                o.Name: {
                    "bounds": str(o.Shape.BoundBox),
                    "volume": o.Shape.Volume,
                    "placement": str(o.Placement),
                }
                for o in source_members + list(insertion.representation(first).Group)
            },
            indent=2,
        )
    )
    parent.save()
    from freecad.forgepdm import fcstd

    check(
        "Saved archive retains every managed external reference",
        len(fcstd.inspect(parent.FileName)[1]) == 8,
    )
    path = parent.FileName
    App.closeDocument(parent.Name)
    parent = App.openDocument(path)
    parent.recompute()
    check(
        "Save and reopen preserve complete occurrences and BOM",
        len(cad.capture_bom(parent)) == 2
        and len(parent.Component.Shape.Solids) == sum(len(o.Shape.Solids) for o in source_members),
    )
    group = insertion.representation(parent.Component)
    original = group.ForgePDMRepresentation
    group.ForgePDMRepresentation = "{}"
    try:
        cad.capture_bom(parent)
    except insertion.WorkspaceError:
        check("Damaged representation blocks BOM extraction", True)
    else:
        raise AssertionError("Damaged representation accepted")
    group.ForgePDMRepresentation = original
    import shutil
    from freecad.forgepdm import replacement

    replacement_path = Path(source.FileName).with_name("insertion-replacement.FCStd")
    shutil.copyfile(source.FileName, replacement_path)
    next_source = App.openDocument(str(replacement_path))
    commands._set_metadata(next_source, RevisionId="replacement-revision")
    next_source.recompute()
    cad.settle_techdraw(next_source)
    next_source.recompute()
    cad.settle_techdraw(next_source)
    next_source.recompute()
    cad.settle_techdraw(next_source)
    next_source.commitTransaction()
    Gui.getDocument(next_source.Name).save()
    parent.commitTransaction()

    def states():
        return {
            d.Name: {
                "touched": d.isTouched(),
                "modified": Gui.getDocument(d.Name).Modified,
                "objects": [o.Name for o in d.Objects if "Touched" in o.State],
            }
            for d in App.listDocuments().values()
        }

    before_states = states()
    replacement.apply(
        parent,
        cad.capture_bom(parent),
        [parent.Component.Name],
        next_source,
        {"id": "replacement-revision", "item_id": next_source.ForgePDM_Metadata.ItemId},
    )
    import json

    (directory / "states.json").write_text(
        json.dumps({"before": before_states, "after": states()}, indent=2)
    )
    check(
        "Native replacement retains occurrence and complete members",
        insertion.source(parent.Component).Document is next_source
        and len(cad.capture_bom(parent)) == 2,
    )
    part_document = next(
        d
        for d in App.listDocuments().values()
        if d.getObject("ForgePDM_Metadata") and d.ForgePDM_Metadata.ItemNumber.startswith("P")
    )
    candidates = insertion.part_targets(part_document)
    part_occurrence = insertion.insert(parent, part_document, "Part", candidates[0])
    check(
        "Part insertion uses a direct native external link",
        part_occurrence.LinkedObject is candidates[0] and not part_occurrence.Shape.isNull(),
    )
    check(
        "Parts and subassemblies retain separate direct BOM entries",
        len(cad.capture_bom(parent)) == 3,
    )
    check(
        "Source snapshot bytes preserved",
        all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p, h in hashes.items()),
    )
    return {
        "checks": checks,
        "freecad": App.Version(),
        "source_mutated": False,
        "server_mutations": False,
    }
