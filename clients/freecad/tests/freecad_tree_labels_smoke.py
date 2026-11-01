"""Real CAD persistence/observer tests on disposable documents, no server writes.

Invoke run(App, Gui) through MCP. The observer lease is injected only for the
disposable fixture; the actual refresh command separately verifies real leases.
"""


def run(App, Gui, report_path="/tmp/forgepdm-tree-labels-report.json"):
    import json
    from pathlib import Path
    import sys
    import tempfile
    from datetime import datetime, timedelta, timezone
    from uuid import uuid4

    import freecad.forgepdm as package
    from freecad.forgepdm import commands, session, tree_labels, tree_observer, ui

    original_names = set(App.listDocuments())
    active = App.ActiveDocument.Name if App.ActiveDocument else None
    directory = Path(tempfile.mkdtemp(prefix="forgepdm-tree-labels-"))
    server = session.Session.client.base_url
    report = {
        "freecad": App.Version(),
        "python": sys.version,
        "qt": ui.QtCore.qVersion(),
        "addon_version": package.__version__,
        "checks": [],
        "scope": "Disposable real FreeCAD documents, save/reopen and observer; injected fixture lease; no backend writes",
    }

    def check(label, value):
        assert value, label
        report["checks"].append(label)

    def document(name, number, revision):
        doc = App.newDocument(name)
        commands._set_metadata(
            doc,
            ItemId=str(uuid4()),
            RevisionId=str(uuid4()),
            ItemNumber=number,
            RevisionLabel=revision,
            ServerUrl=server,
        )
        doc.saveAs(str(directory / (name + ".FCStd")))
        return doc

    def wait(milliseconds=700):
        loop = ui.QtCore.QEventLoop()
        ui.QtCore.QTimer.singleShot(milliseconds, loop.quit)
        loop.exec()

    def refresh(doc):
        # Direct Python fixture edits need the commit normally performed by the native GUI command.
        if doc.HasPendingTransaction:
            doc.commitTransaction()
        return tree_labels.refresh(doc)

    def link(doc, parent, target, name):
        obj = doc.addObject("App::Link", name)
        obj.setLink(target)
        parent.addObject(obj)
        return obj

    try:
        child = document("TreeTestPart", "P999901", "B")
        box = child.addObject("Part::Box", "Box")
        box.Length, box.Width, box.Height = 10, 2, 3
        child.recompute()
        Gui.getDocument(child.Name).save()
        child_label = child.Label
        volume = box.Shape.Volume
        root = document("TreeTestAssembly", "A999901", "A")
        group = root.addObject("Assembly::AssemblyObject", "Assembly")
        first = link(root, group, box, "First")
        second = link(root, group, box, "Second")
        second.Placement.Base = App.Vector(20, 0, 0)
        root.recompute()
        first_name, second_name = first.Name, second.Name
        refresh(root)
        first_id, second_id = first.ForgePDMOccurrenceId, second.ForgePDMOccurrenceId
        check(
            "repeated components get distinct stable occurrence labels",
            first.Label == "P999901-B|1" and second.Label == "P999901-B|2",
        )
        check(
            "labels do not change object names or link identity",
            first.Name == first_name
            and second.Name == second_name
            and first.LinkedObject is box
            and second.LinkedObject is box,
        )
        check(
            "source part and placements stay unchanged",
            child.Label == child_label
            and second.Placement.Base.x == 20
            and box.Shape.Volume == volume
            and not Gui.getDocument(child.Name).Modified,
        )
        root.removeObject(first.Name)
        refresh(root)
        check(
            "surviving occurrence is not renumbered after deletion",
            second.Label == "P999901-B|2" and second.ForgePDMOccurrenceId == second_id,
        )
        copy = root.copyObject(second, False)
        group.addObject(copy)
        root.commitTransaction()
        refresh(root)
        check(
            "native copied link gets fresh UUID and next occurrence",
            copy.Label == "P999901-B|3" and copy.ForgePDMOccurrenceId not in (first_id, second_id),
        )
        root.removeObject(copy.Name)
        new = link(root, group, box, "New")
        refresh(root)
        check("deleted highest occurrence number is not reused", new.Label == "P999901-B|4")
        group.Group = list(reversed(group.Group))
        refresh(root)
        check(
            "tree reordering preserves occurrence numbers",
            second.Label == "P999901-B|2" and new.Label == "P999901-B|4",
        )

        sub = document("TreeTestSubassembly", "A999902", "C")
        sub_group = sub.addObject("App::Part", "SubAssembly")
        sub_link = link(sub, sub_group, box, "SubPart")
        refresh(sub)
        sub.recompute()
        Gui.getDocument(sub.Name).save()
        assembly_link = link(root, group, sub_group, "Subassembly")
        refresh(root)
        check(
            "external subassembly has its own parent occurrence",
            assembly_link.Label == "A999902-C|1",
        )
        check(
            "subassembly child numbering restarts in its own scope", sub_link.Label == "P999901-B|1"
        )

        root.recompute()
        Gui.getDocument(root.Name).save()
        root_path = root.FileName
        ids = {
            obj.Name: (obj.ForgePDMOccurrenceId, obj.ForgePDMOccurrenceNumber, obj.Label)
            for obj in root.Objects
            if obj.TypeId == "App::Link"
        }
        name = root.Name
        App.closeDocument(name)
        root = App.openDocument(root_path)
        check(
            "save/reopen preserves UUIDs, numbers and labels",
            ids
            == {
                obj.Name: (obj.ForgePDMOccurrenceId, obj.ForgePDMOccurrenceNumber, obj.Label)
                for obj in root.Objects
                if obj.TypeId == "App::Link"
            },
        )
        before_label = root.Label
        before_state = root.getObject("ForgePDM_Metadata").TreeOccurrenceState
        refresh(root)
        report["reopen_diagnostic"] = {
            "label_before": before_label,
            "label_after": root.Label,
            "registry_changed": before_state
            != root.getObject("ForgePDM_Metadata").TreeOccurrenceState,
        }
        check(
            "raw reopen preserves the occurrence registry",
            not report["reopen_diagnostic"]["registry_changed"],
        )
        check(
            "managed refresh reapplies document heading without reallocating",
            root.Label == "A999901-A",
        )
        check("repeat refresh on the opened document is a no-op", not refresh(root)["changed"])
        group = root.getObject("Assembly")
        second = root.getObject(second_name)
        new = root.getObject("New")

        # No network is involved in the fixture lease. Production commands verify
        # the same payload using the authenticated checkout API before granting it.
        checkout = {
            "user_id": session.Session.user["id"],
            "revision_id": root.getObject("ForgePDM_Metadata").RevisionId,
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        }
        tree_observer.allow_edit(root, checkout, session.Session.client, session.Session.user)
        root.openTransaction("Native insertion regression")
        inserted = link(root, group, box, "Inserted")
        root.commitTransaction()
        root.recompute()
        wait()
        check(
            "native insertion is automatically labeled after transaction completion",
            inserted.Label == "P999901-B|5",
        )
        check(
            "automatic labeling leaves existing indices stable",
            second.Label == "P999901-B|2" and new.Label == "P999901-B|4",
        )
        metadata = child.getObject("ForgePDM_Metadata")
        metadata.RevisionId, metadata.RevisionLabel = str(uuid4()), "C"
        wait()
        check(
            "explicit target revision changes display without latest lookup",
            second.Label == "P999901-C|1" and second.ForgePDMOccurrenceId == second_id,
        )
        tree_observer.revoke_revision(root.getObject("ForgePDM_Metadata").RevisionId)
        unowned = link(root, group, box, "WithoutLease")
        wait()
        check(
            "insertion after checkout revocation is not automatically modified",
            not hasattr(unowned, "ForgePDMOccurrenceId"),
        )
        check(
            "source geometry remains unchanged through all label operations",
            box.Shape.Volume == volume,
        )
        report["status"] = "passed"
    except BaseException as error:
        report.update({"status": "failed", "error": str(error)})
        raise
    finally:
        for name in list(App.listDocuments()):
            if name not in original_names:
                doc = App.getDocument(name)
                metadata = doc.getObject("ForgePDM_Metadata")
                if metadata:
                    tree_observer.revoke_revision(metadata.RevisionId)
                App.closeDocument(name)
        if active:
            App.setActiveDocument(active)
        Path(report_path).write_text(json.dumps(report, indent=2) + "\n")
    return report
