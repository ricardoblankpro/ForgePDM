"""Disposable native AssemblyLink replacement/constraint rollback probe via MCP."""


def run(App, Gui, constrained=False):
    from pathlib import Path
    from uuid import uuid4
    import tempfile
    from freecad.forgepdm import commands, cad, replacement

    folder = Path(tempfile.mkdtemp(prefix="forgepdm-native-replace-"))
    owned = []
    previous = App.ActiveDocument.Name if App.ActiveDocument else None
    try:
        item = str(uuid4())
        a = str(uuid4())
        b = str(uuid4())
        rootid = str(uuid4())
        sources = []
        for label, revision, length in [("A", a, 10), ("B", b, 20)]:
            d = App.newDocument("NativeReplacementSource" + label)
            owned.append(d)
            commands._set_metadata(
                d,
                ItemId=item,
                RevisionId=revision,
                ItemNumber="SUB",
                RevisionLabel=label,
                ServerUrl="http://native-test",
            )
            group = d.addObject("Assembly::AssemblyObject", "Assembly")
            shape = d.addObject("Part::Box", "Box")
            shape.Length = length
            group.addObject(shape)
            d.recompute()
            d.saveAs(str(folder / (label + ".FCStd")))
            if d.HasPendingTransaction:
                d.commitTransaction()
            d.recompute()
            Gui.getDocument(d.Name).save()
            sources.append(d)
        root = App.newDocument("NativeReplacementOuter")
        owned.append(root)
        root.saveAs(str(folder / "root.FCStd"))
        commands._set_metadata(
            root,
            ItemId=rootid,
            RevisionId=str(uuid4()),
            ItemNumber="ROOT",
            RevisionLabel="A",
            ServerUrl="http://native-test",
        )
        group = root.addObject("Assembly::AssemblyObject", "Assembly")
        link = root.addObject("Assembly::AssemblyLink", "Sub")
        link.LinkedObject = sources[0].getObject("Assembly")
        group.addObject(link)
        root.recompute()
        if constrained:
            import JointObject

            grounded = root.addObject("App::FeaturePython", "Grounded")
            JointObject.GroundedJoint(grounded, link.Group[0])
            joints = root.addObject("Assembly::JointGroup", "Joints")
            group.addObject(joints)
            joints.addObject(grounded)
        root.recompute()
        root.saveAs(str(folder / "root.FCStd"))
        if root.HasPendingTransaction:
            root.commitTransaction()
        root.recompute()
        Gui.getDocument(root.Name).save()
        print(
            "Before native replacement",
            [(c.Name, c.TypeId, str(getattr(c, "LinkedObject", None))) for c in link.Group],
        )
        refs = cad.capture_bom(root)
        if constrained:
            try:
                replacement.apply(root, refs, ["Sub"], sources[1], {"id": b, "item_id": item})
            except replacement.WorkspaceError:
                assert root.getObject("Sub").LinkedObject is sources[0].getObject("Assembly")
                assert root.getObject("Grounded").ObjectToGround is not None
                return {"status": "passed", "constrained_rollback": True}
            else:
                raise AssertionError("Generated-child joint replacement needs explicit mapping")
        replacement.apply(root, refs, ["Sub"], sources[1], {"id": b, "item_id": item})
        print(
            "After native replacement",
            [(c.Name, c.TypeId, str(getattr(c, "LinkedObject", None))) for c in link.Group],
        )
        assert link.LinkedObject is sources[1].getObject("Assembly")
        for c in link.Group:
            if c.TypeId == "App::Link":
                assert c.LinkedObject.Document is sources[1]
        return {"status": "passed", "native_target_and_generated_child_pins": True}
    finally:
        for d in reversed(owned):
            App.closeDocument(d.Name)
        if previous:
            App.setActiveDocument(previous)
