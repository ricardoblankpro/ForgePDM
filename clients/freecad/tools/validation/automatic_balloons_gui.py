"""Disposable native picking, observer events, persistence and authorization fixtures."""


def run(App, Gui, directory):
    import json
    from pathlib import Path
    from types import SimpleNamespace
    import Part
    from freecad.forgepdm import cad
    from freecad.forgepdm import (
        balloon_geometry as geometry,
        balloon_auto as auto,
        drawing_bom as bom,
        drawing_balloons as links,
        commands,
        workspace,
        tasks,
    )
    from freecad.forgepdm.session import Session
    from freecad.forgepdm.ui import QtCore

    case = Path(directory)
    assert case.name.startswith("forgepdm-auto-balloons-qa") and not App.listDocuments()
    case.mkdir(parents=True, exist_ok=True)
    original = Session.client, Session.user, Session.busy
    choice_original = auto.choose
    auto.choose = lambda *args, **kwargs: 0
    binding, working, runner = workspace.binding, workspace.working_path, tasks.run

    class Checks(list):
        def append(self, value):
            super().append(value)
            (case / "progress.json").write_text(json.dumps(self))

    docs, checks = [], Checks()
    observer = auto._observer or auto.Observer()
    owned_observer = auto._observer is None
    if owned_observer:
        App.addDocumentObserver(observer)
    observer.suspended = True

    def drive(flow):
        value = None
        while True:
            try:
                request = flow.send(value)
            except StopIteration:
                return
            value = request.function(*request.args, **request.kwargs)

    try:
        root = App.newDocument("AutoBalloonsQA")
        docs.append(root)
        root.UndoMode = 1
        commands._set_metadata(
            root, ItemId="fixture-item", RevisionId="root", ItemNumber="A1", RevisionLabel="A"
        )
        root.saveAs(str(case / "root.FCStd"))
        occurrences = []
        for i, offset in enumerate((0, 25)):
            doc = App.newDocument("AutoPartQA" + str(i))
            docs.append(doc)
            part = doc.addObject("PartDesign::Feature", "Part")
            part.Shape = Part.makeBox(10, 10, 10)
            commands._set_metadata(
                doc,
                ItemId="part" + str(i),
                RevisionId="revision" + str(i),
                ItemNumber="P" + str(i),
                RevisionLabel="A",
            )
            doc.recompute()
            doc.saveAs(str(case / ("part" + str(i) + ".FCStd")))
            obj = root.addObject("App::Link", "Occurrence" + str(i))
            obj.setLink(part)
            obj.Placement.Base = App.Vector(offset, 0, 0)
            occurrences.append(obj)
        App.setActiveDocument(root.Name)
        page = root.addObject("TechDraw::DrawPage", "Page")
        template = root.addObject("TechDraw::DrawSVGTemplate", "Template")
        path = case / "template.svg"
        path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="297mm" height="210mm" viewBox="0 0 297 210"/>'
        )
        template.Template = str(path)
        page.Template = template
        view = root.addObject("TechDraw::DrawViewPart", "View")
        view.Source = occurrences
        view.Direction = (0, 0, 1)
        page.addView(view)
        report = dict(
            revision_id="root",
            item_number="A1",
            revision_label="A",
            view="direct",
            lines=[
                dict(
                    component_revision_id="revision" + str(i),
                    position=5 + i,
                    item_number="P" + str(i),
                    revision_label="A",
                    description="Fixture",
                    quantity="1",
                )
                for i in range(2)
            ],
        )
        table = bom.apply(root, page, None, report, bom.DEFAULT, {}, 148.5, 40)
        balloon = root.addObject("TechDraw::DrawViewBalloon", "Balloon")
        balloon.SourceView = view
        page.addView(balloon)
        root.recompute()
        for direction in [(0, 0, 1), (0, 1, 0), (1, -1, 1)]:
            view.Direction = direction
            view.Rotation = 33
            view.Scale = 2
            root.recompute()
            pt = view.projectPoint(App.Vector(5, 5, 5) - view.getGeometricCenter())
            balloon.OriginX, balloon.OriginY = pt.x, pt.y
            assert [o.Name for o, r in geometry.pick(balloon)] == ["Occurrence0"]
        checks.append(
            "Orthographic/isometric rotated and scaled views identify the correct pinned occurrence"
        )
        view.Direction = (0, 0, 1)
        view.Rotation = 0
        view.Scale = 1
        root.recompute()

        def point(world):
            pt = view.projectPoint(world - view.getGeometricCenter())
            balloon.OriginX, balloon.OriginY = pt.x, pt.y

        point(App.Vector(5, 5, 5))
        assert len(geometry.candidates(balloon, bom.read_table(table))) == 1
        checks.append("Solid interiors resolve without requiring an edge selection")
        from datetime import datetime, timedelta, timezone

        lease = dict(
            id="fixture",
            version=1,
            user_id="actor",
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        )
        Session.client = SimpleNamespace(
            token="fixture",
            base_url="http://fixture",
            get_revision=lambda _: dict(item_id="fixture-item", lifecycle_state="working"),
            bom_snapshot=lambda _: {},
            get_checkout=lambda _: lease.copy(),
        )
        Session.user = {"id": "actor"}
        workspace.binding = lambda *a, **k: {}
        workspace.working_path = lambda *a, **k: root.FileName

        def run_fixture(flow):
            Session.busy = True
            try:
                return drive(flow)
            finally:
                Session.busy = False

        tasks.run = run_fixture
        observer.suspended = False
        observer.queue(balloon)
        cad.settle_techdraw(root)
        observer.flush()
        assert balloon.Text == "5" and links.issues(page) == [], (
            balloon.Text,
            links.issues(page),
            observer.pending,
        )
        checks.append(
            "Native creation/property events trigger authorized automatic adoption through the observer"
        )
        root.openTransaction("Native arrow movement")
        point(App.Vector(30, 5, 5))
        root.commitTransaction()
        observer.flush()
        assert balloon.Text == "6" and json.loads(balloon.PDMBOMBinding)["format"] == 3
        assert bom.read_table(table)["format"] == 7
        checks.append(
            "Moving the arrow retargets the existing native balloon to the second BOM Position"
        )
        root.undo()
        root.recompute()
        assert not observer.pending
        root.redo()
        root.recompute()
        assert balloon.Text == "6" and not observer.pending
        checks.append(
            "Undo/redo suppress observer replay and preserve separate native/link transactions"
        )
        saved = geometry.signature(balloon)
        observer.pending.clear()
        balloon.X = 100
        observer.flush()
        assert not observer.pending and geometry.signature(balloon) == saved
        checks.append("Bubble-only movement does not retarget")
        root.recompute()
        root.save()
        cad.settle_techdraw(root)
        (case / "stage.txt").write_text("before close")
        table_name = table.Name
        root_name = root.Name
        App.closeDocument(root_name)
        docs.remove(root)
        (case / "stage.txt").write_text("before reopen")
        root = App.openDocument(str(case / "root.FCStd"))
        docs.insert(0, root)
        (case / "stage.txt").write_text("after reopen")
        root.recompute()
        balloon = root.getObject("Balloon")
        view = root.getObject("View")
        page = root.getObject("Page")
        table = root.getObject(table_name)
        assert not observer.pending and links.issues(page) == [], links.issues(page)
        checks.append(
            "Save/reopen retains attachment evidence and does not automatically adopt restored objects"
        )
        import TechDrawGui
        from freecad.forgepdm import fcstd

        cad.settle_techdraw(root)
        TechDrawGui.exportPageAsPdf(page, str(case / "automatic-balloons.pdf"))
        assert (case / "automatic-balloons.pdf").read_bytes().startswith(b"%PDF-")
        _, references = fcstd.inspect(root.FileName)
        assert len(references) == 2
        checks.append(
            "Format-7 native drawing passes FCStd reference inspection and real PDF rendering"
        )
        observer.suspended = True
        balloon.OriginX = 500
        assert links.issues(page)
        observer.pending.clear()
        balloon.OriginX = 0
        balloon.OriginY = 0
        root.recompute()
        view.Perspective = True
        try:
            geometry.pick(balloon)
        except ValueError:
            pass
        else:
            raise AssertionError("Perspective accepted")
        view.Perspective = False
        checks.append(
            "Changed attachments block PDF preflight; unsupported perspective is rejected"
        )
        observer.pending.clear()
        observer.suspended = False
        cad.settle_techdraw(root)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(view, "Edge1")
        prior = {obj.Name for obj in root.Objects}
        (case / "stage.txt").write_text("before native command")
        Gui.runCommand("TechDraw_Balloon", 0)
        (case / "stage.txt").write_text("after native command")
        if Gui.getDocument(root.Name).getInEdit():
            Gui.getDocument(root.Name).resetEdit()
        created = [
            obj
            for obj in root.Objects
            if obj.Name not in prior and obj.TypeId == "TechDraw::DrawViewBalloon"
        ]
        assert len(created) == 1, "Native balloon command did not create a balloon"
        observer.flush()
        assert created[0].PDMBOMStatus == "Linked"
        checks.append(
            "Actual TechDraw_Balloon command on a selected projected edge automatically links via native observer events"
        )
        Gui.Selection.clearSelection()
        overlap = root.getObject("Occurrence1")
        overlap.Placement.Base = App.Vector(0, 0, 20)
        root.recompute()
        pt = view.projectPoint(App.Vector(5, 5, 5) - view.getGeometricCenter())
        balloon.OriginX, balloon.OriginY = pt.x, pt.y
        assert len(geometry.pick(balloon)) == 2
        checks.append("Overlapping projections retain both candidates instead of guessing depth")
        result = dict(
            freecad=App.Version()[:3],
            qt=QtCore.qVersion(),
            checks=checks,
            scope="Disposable native documents; permission/checkout/workspace/worker fixtures, no HTTP publication or production writes",
        )
        (case / "report.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result))
        return result
    finally:
        auto.choose = choice_original
        if owned_observer:
            App.removeDocumentObserver(observer)
        observer.pending.clear()
        observer.suspended = False
        observer.timer.stop()
        workspace.binding, workspace.working_path, tasks.run = binding, working, runner
        Session.client, Session.user, Session.busy = original
        for doc in docs:
            if doc.Name in App.listDocuments():
                App.closeDocument(doc.Name)
