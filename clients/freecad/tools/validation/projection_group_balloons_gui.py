"""Native projection-group containment regression; all mutations are disposable."""


def run(App, Gui, directory):
    import json
    from pathlib import Path
    from uuid import uuid4
    import Part
    import TechDrawGui
    from freecad.forgepdm import (
        cad,
        drawing_balloons as links,
        drawing_bom as bom,
        balloon_geometry as geometry,
        balloon_auto,
    )
    from freecad.forgepdm.session import Session

    case = Path(directory)
    assert case.name.startswith("forgepdm-projection-balloon-qa")
    case.mkdir(parents=True, exist_ok=True)
    active = App.ActiveDocument.Name if App.ActiveDocument else None
    session = Session.client, Session.user
    observer = balloon_auto._observer
    suspended = observer.suspended if observer else None
    if observer:
        observer.suspended = True
    owned = []
    checks = []
    try:
        doc = App.newDocument("ProjectionBalloonQA" + uuid4().hex[:6])
        owned.append(doc)
        doc.UndoMode = 1
        doc.saveAs(str(case / "root.FCStd"))
        partdoc = App.newDocument("ProjectionPartQA" + uuid4().hex[:6])
        owned.append(partdoc)
        part = partdoc.addObject("PartDesign::Feature", "Part")
        part.Shape = Part.makeBox(10, 10, 10)
        meta = partdoc.addObject("App::FeaturePython", "ForgePDM_Metadata")
        meta.addProperty("App::PropertyString", "RevisionId")
        meta.RevisionId = "part-A"
        partdoc.recompute()
        partdoc.saveAs(str(case / "part.FCStd"))
        link = doc.addObject("App::Link", "Occurrence")
        link.setLink(part)
        page = doc.addObject("TechDraw::DrawPage", "Page")
        template = doc.addObject("TechDraw::DrawSVGTemplate", "Template")
        path = case / "template.svg"
        path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="297mm" height="210mm" viewBox="0 0 297 210"/>'
        )
        template.Template = str(path)
        page.Template = template
        group = doc.addObject("TechDraw::DrawProjGroup", "Projections")
        group.Source = [link]
        created_view = group.addProjection("Front")
        view = doc.getObject(created_view.Name)
        page.addView(group)
        doc.recompute()
        cad.settle_techdraw(doc)
        balloon = doc.addObject("TechDraw::DrawViewBalloon", "Balloon")
        balloon.SourceView = view
        page.addView(balloon)
        point = view.projectPoint(App.Vector(5, 5, 5) - view.getGeometricCenter())
        balloon.OriginX, balloon.OriginY = point.x, point.y
        report = dict(
            revision_id="root",
            item_number="A1",
            revision_label="A",
            view="direct",
            lines=[
                dict(
                    component_revision_id="part-A",
                    position=5,
                    item_number="P1",
                    revision_label="A",
                    quantity="1",
                    description="Fixture",
                )
            ],
        )
        table = bom.apply(doc, page, None, report, bom.DEFAULT, {}, 148.5, 40)
        # Reproduce saved pages where only the projection group is listed.
        page.Views = [obj for obj in page.Views if obj is not view]
        assert view.Name not in [o.Name for o in page.Views]
        assert group.Name in [o.Name for o in page.Views]
        assert view.Name in [o.Name for o in group.Views]

        checks.append(
            "Real projected source belongs through DrawProjGroup.Views instead of page.Views"
        )
        links.bind(doc, page, balloon, table, "part-A:5")
        assert balloon.Text == "5" and links.issues(page) == []
        checks.append("Manual linking and PDF preflight accept the grouped source view")
        attachment = dict(component=link.Name, geometry=geometry.evidence(balloon))
        links.bind(doc, page, balloon, table, "part-A:5", attachment)
        assert (
            balloon.Text == "5"
            and links.issues(page) == []
            and bom.read_table(table)["format"] == 6
        )
        checks.append(
            "Geometry-based automatic binding and preflight accept the real grouped source"
        )
        other = doc.addObject("TechDraw::DrawPage", "OtherPage")
        assert not links.source_on_page(other, view)
        checks.append("A page without the projection group still rejects its child source")
        bom.apply(
            doc, page, table, report, {**bom.DEFAULT, "sort_order": "descending"}, {}, 148.5, 40
        )
        assert links.issues(page) == []
        doc.recompute()
        cad.settle_techdraw(doc)
        doc.save()
        rootname = doc.Name
        App.closeDocument(rootname)
        owned.remove(doc)
        doc = App.openDocument(str(case / "root.FCStd"))
        owned.insert(0, doc)
        doc.recompute()
        cad.settle_techdraw(doc)
        page = doc.getObject("Page")
        assert links.issues(page) == [] and doc.getObject("Balloon").Text == "5"
        checks.append("Explicit table update and native save/reopen retain the grouped link")
        TechDrawGui.exportPageAsPdf(page, str(case / "grouped-balloon.pdf"))
        assert (case / "grouped-balloon.pdf").read_bytes().startswith(b"%PDF-")
        checks.append("Native PDF rendering succeeds for the reopened grouped drawing")
        result = dict(
            freecad=App.Version()[:3],
            checks=checks,
            scope="Disposable native drawing only; no session/HTTP/server mutation",
        )
        (case / "report.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result))
        return result
    finally:
        for doc in owned:
            if doc.Name in App.listDocuments():
                App.closeDocument(doc.Name)
        if observer:
            observer.suspended = suspended
        if active and active in App.listDocuments():
            App.setActiveDocument(active)
        assert (Session.client, Session.user) == session
