"""Native links, transactions, offline persistence and PDF guards on disposable CAD."""


def run(App, Gui, directory, prior_model_path=None):
    import copy
    import importlib.util
    import json
    from pathlib import Path
    from uuid import uuid4

    import Part
    import TechDrawGui
    from freecad.forgepdm import __version__, drawing_balloons as links, drawing_bom as bom
    from freecad.forgepdm.drawing_balloons_ui import LinkBalloonDialog
    from freecad.forgepdm.session import Session
    from freecad.forgepdm.ui import QtCore

    case = Path(directory)
    assert case.name.startswith("forgepdm-drawing-balloons-qa")
    case.mkdir(parents=True, exist_ok=True)
    assert not Session.busy and not App.listDocuments(), "Run in an idle empty FreeCAD session"
    original_session = Session.client, Session.user
    checks, document, dialog = [], None, None
    report = dict(
        revision_id="fixture-root",
        item_number="A1",
        revision_label="A",
        view="direct",
        token="frozen",
        language="en",
        lines=[
            dict(
                component_revision_id=part,
                position=pos,
                item_number=part,
                revision_label="A",
                description="Plate",
                quantity="2",
            )
            for part, pos in [("P10", 5), ("P2", 8)]
        ],
    )
    try:
        document = App.newDocument("DrawingBalloonsQA" + uuid4().hex[:8])
        document.UndoMode = 1
        page = document.addObject("TechDraw::DrawPage", "Page")
        template = document.addObject("TechDraw::DrawSVGTemplate", "Template")
        template_path = case / "template.svg"
        template_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="297mm" height="210mm" viewBox="0 0 297 210"><rect x="5" y="5" width="287" height="200" fill="none" stroke="black"/></svg>'
        )
        template.Template = str(template_path)
        page.Template = template
        part = document.addObject("PartDesign::Feature", "Part")
        part.Shape = Part.makeBox(30, 20, 10)
        view = document.addObject("TechDraw::DrawViewPart", "View")
        view.Source = [part]
        view.Direction = (0, 0, 1)
        view.X, view.Y = 75, 140
        page.addView(view)
        document.recompute()
        table = bom.apply(document, page, None, report, bom.DEFAULT, {}, 148.5, 50)
        other = bom.apply(document, page, None, report, bom.DEFAULT, {}, 148.5, 90)
        balloon = document.addObject("TechDraw::DrawViewBalloon", "Balloon")
        balloon.SourceView = view
        balloon.Text = "literal"
        balloon.OriginX, balloon.OriginY = 5, 5
        balloon.X, balloon.Y = 35, 25
        balloon.BubbleShape = "Hexagon"
        page.addView(balloon)
        document.recompute()

        def placement():
            return (
                balloon.SourceView,
                float(balloon.X),
                float(balloon.Y),
                float(balloon.OriginX),
                float(balloon.OriginY),
                balloon.BubbleShape,
                balloon.EndType,
            )

        original_placement = placement()
        before = table.PDMTableData
        dialog = LinkBalloonDialog(None, [page], balloon)
        assert dialog.grid.item(0, 1).text() == "P2"
        dialog.accept()
        assert dialog.result() == 0
        dialog.grid.selectRow(1)
        key = dialog.row_key()
        dialog.accept()
        assert dialog.result() == 1
        links.bind(document, page, balloon, table, key)
        assert balloon.Text == "5" and links.issues(page) == []
        assert placement() == original_placement
        checks.append(
            "Native adoption dialog selects an exact sorted frozen entry; expression displays BOM Position and retains leader/style"
        )
        document.undo()
        document.recompute()
        assert table.PDMTableData == before and balloon.Text == "literal"
        assert not hasattr(balloon, "PDMBOMBinding")
        document.redo()
        document.recompute()
        assert balloon.Text == "5" and links.issues(page) == []
        checks.append("Adoption, table format and native properties undo/redo atomically")
        data = bom.read_table(table)
        assert data["format"] == 5 and data["report"] == report
        if prior_model_path:
            spec = importlib.util.spec_from_file_location(
                "freecad.forgepdm._previous_bom", prior_model_path
            )
            previous = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(previous)
            try:
                previous.read_table(table)
            except ValueError as error:
                assert "Unsupported saved drawing BOM format" in str(error)
            else:
                raise AssertionError("Previous addon accepted a linked table")
            checks.append(
                "Previous addon rejects editing format 5 while embedded SVG remains native"
            )
        changed = copy.deepcopy(report)
        changed.update(language="pt-BR", token="translated")
        changed["lines"][0].update(description="Chapa", id="recreated-db-line", quantity="4")
        definition = {**bom.DEFAULT, "sort_order": "descending"}
        frozen_other = other.PDMTableData
        bom.apply(document, page, table, changed, definition, {}, 148.5, 50)
        assert balloon.Text == "5" and links.issues(page) == []
        assert other.PDMTableData == frozen_other and placement() == original_placement
        checks.append(
            "Sort, translation, quantity and recreated EBOM UUIDs preserve the exact link and other tables"
        )
        frozen = table.PDMTableData, table.Symbol, balloon.PDMBOMBinding
        refresh = links.refresh

        def fail(*args):
            raise RuntimeError("Injected transaction failure")

        links.refresh = fail
        try:
            try:
                bom.apply(document, page, table, report, bom.DEFAULT, {}, 148.5, 50)
            except RuntimeError:
                pass
            else:
                raise AssertionError("Failure injection did not run")
        finally:
            links.refresh = refresh
        assert (table.PDMTableData, table.Symbol, balloon.PDMBOMBinding) == frozen
        checks.append("Failed table/balloon updates roll back their SVG, report and binding")
        second = document.addObject("TechDraw::DrawViewBalloon", "Balloon2")
        second.SourceView = view
        second.X, second.Y = -30, 20
        page.addView(second)
        links.bind(document, page, second, table, key)
        assert second.Text == "5" and links.issues(page) == []
        literal = document.addObject("TechDraw::DrawViewBalloon", "LegacyBalloon")
        literal.SourceView = view
        literal.Text = "OLD"
        literal.X, literal.Y = 20, -20
        page.addView(literal)
        checks.append("Multiple balloons may reference one exact BOM entry")
        native = case / "linked-balloons.FCStd"
        document.recompute()
        document.saveAs(str(native))
        Gui.getDocument(document.Name).save()
        from freecad.forgepdm import fcstd

        fcstd.validate(native, [])
        checks.append("Native linked FCStd passes managed upload/reference integrity inspection")
        names = table.Name, balloon.Name, second.Name
        frozen = table.PDMTableData, balloon.PDMBOMBinding, list(balloon.ExpressionEngine)
        App.closeDocument(document.Name)
        document = App.openDocument(str(native))
        document.recompute()
        table, balloon, second = [document.getObject(name) for name in names]
        page = document.getObject("Page")
        assert (table.PDMTableData, balloon.PDMBOMBinding, list(balloon.ExpressionEngine)) == frozen
        assert balloon.Text == second.Text == "5" and links.issues(page) == []
        assert balloon.PDMBOMTable is table
        assert document.getObject("LegacyBalloon").Text == "OLD"
        assert not hasattr(document.getObject("LegacyBalloon"), "PDMBOMBinding")
        TechDrawGui.exportPageAsPdf(page, str(case / "linked-balloons.pdf"))
        assert (case / "linked-balloons.pdf").read_bytes().startswith(b"%PDF-")
        checks.append(
            "Native save/reopen/recompute retains frozen links offline and exports linked balloon text to PDF"
        )
        removed = copy.deepcopy(changed)
        removed["lines"][0]["component_revision_id"] = "part-B"
        bom.apply(document, page, table, removed, definition, {}, 148.5, 50)
        assert balloon.Text == second.Text == "?" and len(links.issues(page)) == 2
        document.undo()
        document.recompute()
        assert balloon.Text == second.Text == "5" and links.issues(page) == []
        document.redo()
        document.recompute()
        assert balloon.Text == second.Text == "?"
        checks.append(
            "Changed-revision entries become unresolved together with their table; undo/redo restores all linked numbers"
        )
        links.bind(document, page, balloon, table, bom.row_key(removed["lines"][0]))
        links.bind(document, page, second, table, bom.row_key(removed["lines"][0]))
        assert links.issues(page) == []
        duplicate = copy.deepcopy(removed)
        duplicate["lines"].append({**duplicate["lines"][0], "position": 10})
        bom.apply(document, page, table, duplicate, definition, {}, 148.5, 50)
        assert balloon.Text == "?"
        bom.apply(document, page, table, removed, definition, {}, 148.5, 50)
        assert balloon.Text == "?", "Unresolved links must stay unresolved until explicit adoption"
        checks.append(
            "Duplicate/split occurrences require explicit reconciliation; returning old rows never silently repairs a link"
        )
        links.bind(document, page, balloon, table, bom.row_key(removed["lines"][0]))
        links.bind(document, page, second, table, bom.row_key(removed["lines"][0]))
        document.removeObject(table.Name)
        document.recompute()
        assert len(links.issues(page)) == 2
        checks.append(
            "Deleted tables leave detectable orphan links; literal legacy balloons remain unadopted"
        )
        document.saveAs(str(case / "orphan-balloons.FCStd"))
        App.closeDocument(document.Name)
        document = None
        from freecad.forgepdm import drawing_export
        from freecad.forgepdm.workspace import WorkspaceError

        opener = drawing_export.cad.open_configuration

        def fixture_open(configuration, set_metadata):
            root = App.openDocument(configuration["fixture"])
            return {"root": root, "owned": [root]}

        drawing_export.cad.open_configuration = fixture_open
        try:
            for fixture, valid in [
                ("linked-balloons.FCStd", True),
                ("orphan-balloons.FCStd", False),
            ]:
                destination = case / ("export-valid" if valid else "export-orphan")
                destination.mkdir(exist_ok=True)
                try:
                    drawing_export.export(
                        {"directory": str(case), "fixture": str(case / fixture)},
                        [{"page_name": "Page", "page_label": "Page"}],
                        str(destination),
                        lambda *args, **kwargs: None,
                    )
                except WorkspaceError as error:
                    assert not valid and "Relink BOM balloons" in str(error), str(error)
                else:
                    assert valid, "ForgePDM exported orphan links"
                assert (destination / "page_0001.pdf").exists() == valid
        finally:
            drawing_export.cad.open_configuration = opener
        checks.append(
            "ForgePDM PDF export accepts valid frozen links, rejects orphans before rendering and closes its isolated documents (fixture configuration opener)"
        )
    finally:
        if dialog is not None:
            dialog.deleteLater()
        if document is not None and document.Name in App.listDocuments():
            App.closeDocument(document.Name)
        assert not App.listDocuments() and (Session.client, Session.user) == original_session
    result = dict(
        addon=__version__,
        freecad=App.Version()[:3],
        qt=QtCore.qVersion(),
        checks=checks,
        scope="Disposable CAD only; no backend mutation; initial empty document/session state preserved",
    )
    (case / "native-balloon-report.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result))
    return result
