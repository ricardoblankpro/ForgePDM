"""Real TechDraw sorting, row notes and frozen save/reopen on disposable CAD only."""


def run(App, Gui, directory, prior_model_path=None):
    import copy
    import hashlib
    import importlib.util
    import json
    from pathlib import Path
    from uuid import uuid4
    from xml.etree import ElementTree

    import TechDrawGui
    from freecad.forgepdm import __version__, cad, drawing_bom as model
    from freecad.forgepdm.drawing_bom_ui import DrawingBOMDialog
    from freecad.forgepdm.session import Session
    from freecad.forgepdm.ui import QtCore, QtWidgets

    case = Path(directory)
    assert case.name.startswith("forgepdm-drawing-bom-sort-qa")
    case.mkdir(parents=True, exist_ok=True)
    assert not Session.busy and QtWidgets.QApplication.activeModalWidget() is None
    original_session = Session.client, Session.user
    active = App.ActiveDocument.Name if App.ActiveDocument else None
    selection = [(s.Object, list(s.SubElementNames)) for s in Gui.Selection.getSelectionEx()]

    def documents():
        return {
            d.Name: (
                d.FileName,
                cad.document_modified(d),
                d.isTouched(),
                hashlib.sha256(Path(d.FileName).read_bytes()).hexdigest() if d.FileName else None,
                [
                    (
                        o.Name,
                        o.Label,
                        getattr(o, "Label2", None),
                        getattr(o, "PDMTableData", None),
                        getattr(o, "PDMStandardAssociation", None),
                    )
                    for o in d.Objects
                ],
            )
            for d in App.listDocuments().values()
        }

    def symbol(obj):
        return "".join(obj.Symbol) if isinstance(obj.Symbol, list) else obj.Symbol

    def numbers(obj):
        return [
            node.text
            for node in ElementTree.fromstring(symbol(obj)).iter()
            if node.tag.endswith("text") and node.text in ("P1", "P2", "P10")
        ]

    before = documents()
    checks = []
    document = dialog = None
    report = dict(
        revision_id="fixture-assembly",
        item_number="A000001",
        revision_label="A",
        view="direct",
        language="pt-BR",
        token="frozen-sort-evidence",
        lines=[
            dict(
                component_revision_id=number,
                position=position,
                item_number=number,
                revision_label="A",
                quantity=quantity,
                description="Peça " + number,
                localization={
                    "description": {"source_version": 1, "translation_id": "fixture-" + number}
                },
            )
            for position, number, quantity in [(1, "P10", "10"), (10, "P2", "2"), (2, "P1", "1.5")]
        ],
    )
    source = copy.deepcopy(report)
    try:
        Session.busy = True
        document = App.newDocument("DrawingBOMSortQA" + uuid4().hex[:8])
        page = document.addObject("TechDraw::DrawPage", "Page")
        template = document.addObject("TechDraw::DrawSVGTemplate", "Template")
        template_path = case / "template.svg"
        template_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="297mm" height="210mm" viewBox="0 0 297 210"><rect x="5" y="5" width="287" height="200" fill="none" stroke="black"/></svg>'
        )
        template.Template = str(template_path)
        page.Template = template
        document.recompute()
        dialog = DrawingBOMDialog(None, report, [page])
        assert dialog.sort_by.currentData() == "item_number"
        assert [dialog.grid.item(i, 1).text() for i in range(3)] == ["P1", "P2", "P10"]
        checks.append("Native Drawing BOM editor defaults to ascending natural item numbers")
        dialog.add_column()
        dialog.grid.item(0, 5).setText("Deburr P1")
        dialog.sort_by.setCurrentIndex(dialog.sort_by.findData("quantity"))
        dialog.sort_order.setCurrentIndex(dialog.sort_order.findData("descending"))
        assert [dialog.grid.item(i, 1).text() for i in range(3)] == ["P10", "P2", "P1"]
        assert dialog.grid.item(2, 5).text() == "Deburr P1"
        checks.append("Numeric descending preview keeps custom text attached to its component")
        dialog.x.setValue(148.5)
        dialog.y.setValue(100)
        dialog.accept()
        assert dialog.result() == 1, dialog.status.text()
        table = model.apply(
            document, page, None, dialog.report, dialog.definition(), dialog.notes, 148.5, 100
        )
        saved = model.read_table(table)
        assert saved["format"] == 4 and saved["layout"]["sort_by"] == "quantity"
        assert saved["layout"]["sort_order"] == "descending" and saved["report"] == source
        assert numbers(table) == ["P10", "P2", "P1"]
        assert "Deburr P1" in symbol(table)
        checks.append(
            "Embedded format 4 retains sort policy, original report/token, language provenance and notes"
        )
        if prior_model_path:
            spec = importlib.util.spec_from_file_location(
                "freecad.forgepdm._drawing_bom_previous", prior_model_path
            )
            previous = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(previous)
            try:
                previous.read_table(table)
            except ValueError as error:
                assert "Unsupported saved drawing BOM format" in str(error)
            else:
                raise AssertionError("Previous addon accepted an unsupported sorted table")
            checks.append(
                "Previous addon safely rejects editing format 4 instead of discarding sorting"
            )
        definition = {**saved["layout"], "sort_by": "item_number", "sort_order": "ascending"}
        model.apply(document, page, table, report, definition, saved["notes"], 148.5, 100)
        assert numbers(table) == ["P1", "P2", "P10"]
        checks.append(
            "Explicit item-number sort updates the native SVG while keeping its original notes"
        )
        dialog.deleteLater()
        dialog = None
        frozen = table.PDMTableData, symbol(table)
        table_name = table.Name
        legacy_layout = {
            k: v
            for k, v in model.layout(model.DEFAULT).items()
            if k not in ("sort_by", "sort_order")
        }
        legacy = model.apply(document, page, None, report, legacy_layout, {}, 148.5, 160)
        legacy.PDMTableData = json.dumps(
            dict(format=3, layout=legacy_layout, report=report, notes={})
        )
        legacy_frozen = legacy.PDMTableData, symbol(legacy)
        dialog = DrawingBOMDialog(None, report, [page], preferred=legacy)
        assert dialog.sort_by.currentData() == "bom_order"
        assert [dialog.grid.item(i, 1).text() for i in range(3)] == ["P10", "P2", "P1"]
        dialog.reject()
        dialog.deleteLater()
        dialog = None
        assert (legacy.PDMTableData, symbol(legacy)) == legacy_frozen
        checks.append(
            "Opening a legacy localized table preserves its original layout, row order and embedded bytes"
        )
        assert report == source
        native = case / "sorted-table.FCStd"
        document.recompute()
        document.saveAs(str(native))
        Gui.getDocument(document.Name).save()
        name = document.Name
        App.closeDocument(name)
        document = None
        document = App.openDocument(str(native))
        document.recompute()
        table = document.getObject(table_name)
        assert (table.PDMTableData, symbol(table)) == frozen
        assert numbers(table) == ["P1", "P2", "P10"]
        checks.append(
            "Native FCStd save/reopen/recompute retains sorted SVG and frozen evidence without refetching"
        )
        pdf = case / "sorted-table.pdf"
        TechDrawGui.exportPageAsPdf(document.getObject("Page"), str(pdf))
        assert pdf.read_bytes().startswith(b"%PDF-")
        checks.append("Real TechDraw exports the reopened frozen table to PDF")
    finally:
        if dialog is not None:
            dialog.reject()
            dialog.deleteLater()
        if document is not None and document.Name in App.listDocuments():
            App.closeDocument(document.Name)
        if active and active in App.listDocuments():
            App.setActiveDocument(active)
        Gui.Selection.clearSelection()
        for obj, subs in selection:
            if subs:
                for sub in subs:
                    Gui.Selection.addSelection(obj, sub)
            else:
                Gui.Selection.addSelection(obj)
        Session.busy = False
        assert original_session == (Session.client, Session.user)
        assert documents() == before, "Existing user document state changed"
    checks.append(
        "Original documents, unsaved edits, frozen tables, labels, active document and authenticated session are preserved"
    )
    result = {
        "addon": __version__,
        "freecad": App.Version()[:3],
        "qt": QtCore.qVersion(),
        "checks": checks,
        "scope": "Disposable native documents only; no production CAD or server mutations",
    }
    (case / "native-drawing-bom-sort-report.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result))
    return result
