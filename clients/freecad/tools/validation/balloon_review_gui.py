"""Disposable native diagnostics/marker/PDF probe; never enumerate native scene items."""


def run(App, Gui, directory):
    import hashlib
    import json
    from pathlib import Path

    import TechDrawGui
    from freecad.forgepdm import (
        balloon_auto,
        balloon_geometry,
        balloon_review,
        balloon_review_ui,
        cad,
        commands,
        drawing_balloons,
        drawing_bom,
    )
    from freecad.forgepdm.session import Session
    from freecad.forgepdm.ui import QtWidgets

    assert not Session.busy
    case = Path(directory)
    case.mkdir(parents=True, exist_ok=True)
    previous = set(App.listDocuments())
    active = App.ActiveDocument
    active_view = Gui.activeDocument().activeView() if active else None
    previous_page = active_view.getPage() if hasattr(active_view, "getPage") else None
    selection = [
        (s.DocumentName, s.ObjectName, tuple(s.SubElementNames))
        for s in Gui.Selection.getSelectionEx()
    ]
    client, user = Session.client, Session.user
    observer = balloon_auto._observer
    suspended = observer.suspended if observer else None
    checks, dock, document = [], None, None
    if observer:
        observer.suspended = True

    def check(label, condition):
        assert condition, label
        checks.append(label)

    try:
        document = App.newDocument("BalloonReviewFixture")
        commands._set_metadata(
            document, ItemId="fixture", RevisionId="root", ItemNumber="A1", RevisionLabel="A"
        )
        document.saveAs(str(case / "fixture.FCStd"))
        shape = document.addObject("Part::Box", "Box")
        page = document.addObject("TechDraw::DrawPage", "Page")
        template = document.addObject("TechDraw::DrawSVGTemplate", "Template")
        svg = case / "template.svg"
        svg.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="297mm" height="210mm" viewBox="0 0 297 210"><rect x="1" y="1" width="295" height="208" fill="white" stroke="black"/></svg>'
        )
        template.Template = str(svg)
        page.Template = template
        view = document.addObject("TechDraw::DrawViewPart", "View")
        view.Source, view.Direction, view.X, view.Y = [shape], (0, 0, 1), 70, 120
        page.addView(view)
        group = document.addObject("TechDraw::DrawProjGroup", "Projections")
        group.Source = [shape]
        page.addView(group)
        projected = group.addProjection("Front")
        group.X, group.Y = 180, 120
        report = dict(
            revision_id="root",
            item_number="A1",
            revision_label="A",
            view="direct",
            lines=[
                dict(
                    component_revision_id="part",
                    position=4,
                    item_number="P1",
                    revision_label="A",
                    description="Fixture",
                    quantity="1",
                )
            ],
        )
        table = drawing_bom.apply(document, page, None, report, drawing_bom.DEFAULT, {}, 148, 40)
        balloons = []
        for i, source in enumerate((view, projected, view, projected)):
            balloon = document.addObject("TechDraw::DrawViewBalloon", "Balloon" + str(i))
            balloon.SourceView, balloon.X, balloon.Y = source, -20 + i * 15, 25
            page.addView(balloon)
            document.recompute()
            key = drawing_bom.row_key(report["lines"][0])
            drawing_balloons.bind(document, page, balloon, table, key)
            balloons.append(balloon)
        balloons[0].setExpression("Text", None)
        balloons[0].Text = "wrong"
        balloons[1].PDMBOMTable = None
        binding = json.loads(balloons[2].PDMBOMBinding)
        evidence = balloon_geometry.evidence(balloons[2], legacy=True)
        evidence["scale"] = 2
        binding.update(format=2, attachment={"geometry": evidence, "component": shape.Name})
        balloons[2].PDMBOMBinding = json.dumps(binding)
        document.recompute()
        cad.settle_techdraw(document)
        document.save()
        if document.HasPendingTransaction:
            document.commitTransaction()
        page.ViewObject.show()
        Gui.activeDocument().activeView().fitAll()
        QtWidgets.QApplication.processEvents()
        TechDrawGui.exportPageAsPdf(page, str(case / "before.pdf"))
        baseline = {
            "bindings": [
                (b.PDMBOMBinding, b.Text, tuple(b.ExpressionEngine), b.PDMBOMStatus)
                for b in balloons
            ],
            "table": table.PDMTableData,
            "hash": hashlib.sha256(Path(document.FileName).read_bytes()).hexdigest(),
        }
        dock = balloon_review_ui.ReviewDock(Gui.getMainWindow())
        dock.set_document(document, page)
        dock.show()
        dock.raise_()
        QtWidgets.QApplication.processEvents()
        dock.poll()
        check(
            "Object-aware diagnostics match PDF preflight and ignore the valid balloon",
            [r["balloon"] for r in dock.rows] == balloons[:3]
            and len(drawing_balloons.issues(page)) == 3,
        )
        check(
            "Both ordinary and projection-group bubbles have temporary page markers",
            dock.markers is not None
            and len(dock.markers.points) == 3
            and balloon_review.page_position(balloons[1])
            == (
                float(group.X) + float(projected.X) + float(balloons[1].X) * projected.getScale(),
                float(group.Y) + float(projected.Y) + float(balloons[1].Y) * projected.getScale(),
            ),
        )
        check(
            "Changed view scale has a specific diagnostic",
            "View scale changed" in dock.rows[2]["reason"],
        )
        dock.list.setCurrentRow(1)
        check(
            "Clicking an issue selects its exact native balloon",
            Gui.Selection.getSelection() == [balloons[1]] and dock.markers.selected == 1,
        )
        check(
            "Inspection retains frozen metadata, expressions and saved CAD bytes",
            baseline["bindings"]
            == [
                (b.PDMBOMBinding, b.Text, tuple(b.ExpressionEngine), b.PDMBOMStatus)
                for b in balloons
            ]
            and baseline["table"] == table.PDMTableData
            and baseline["hash"]
            == hashlib.sha256(Path(document.FileName).read_bytes()).hexdigest(),
        )
        TechDrawGui.exportPageAsPdf(page, str(case / "with-markers.pdf"))
        Gui.getMainWindow().grab().save(str(case / "markers.png"))
        dock.hide()
        QtWidgets.QApplication.processEvents()
        check(
            "Closing the panel removes markers and its document observer",
            dock.markers is None and not dock.observing,
        )
        dock.show()
        dock.raise_()
        QtWidgets.QApplication.processEvents()
        dock.refresh()
        drawing_balloons.bind(document, page, balloons[1], table, key)
        if document.HasPendingTransaction:
            document.commitTransaction()
        cad.settle_techdraw(document)
        dock.poll()
        check(
            "A repaired balloon disappears on observer-driven revalidation",
            len(dock.rows) == 2 and all(r["balloon"] is not balloons[1] for r in dock.rows),
        )
        App.closeDocument(document.Name)
        document = None
        dock.poll()
        check(
            "Closing the fixture document clears the issue list and markers",
            dock.list.count() == 0 and dock.markers is None,
        )
    finally:
        if dock is not None:
            dock.hide()
            dock.deleteLater()
        for name in set(App.listDocuments()) - previous:
            App.closeDocument(name)
        if observer:
            observer.suspended = suspended
        if active is not None:
            App.setActiveDocument(active.Name)
            if previous_page is not None:
                previous_page.ViewObject.show()
        Gui.Selection.clearSelection()
        for name, obj, subs in selection:
            for sub in subs or ("",):
                Gui.Selection.addSelection(name, obj, sub)
        assert set(App.listDocuments()) == previous
        assert Session.client is client and Session.user is user and not Session.busy
    result = {
        "checks": checks,
        "freecad": App.Version(),
        "scope": "Disposable native data; no server requests or production-document writes",
    }
    (case / "report.json").write_text(json.dumps(result, indent=2))
    return result
