"""Disposable native title editing, legacy layout, preset and PDF acceptance."""


def run(App, Gui, directory):
    import copy
    import hashlib
    import json
    from pathlib import Path
    from types import SimpleNamespace

    import TechDrawGui
    from freecad.forgepdm import cad, drawing_bom as model, drawing_bom_ui, session, ui

    case = Path(directory)
    case.mkdir(parents=True, exist_ok=True)

    def documents():
        return {
            d.Name: (
                d.FileName,
                cad.document_modified(d),
                hashlib.sha256(Path(d.FileName).read_bytes()).hexdigest() if d.FileName else None,
                [
                    (o.Name, o.PDMTableData, o.Symbol)
                    for o in d.Objects
                    if hasattr(o, "PDMTableData")
                ],
            )
            for d in App.listDocuments().values()
        }

    before = documents()
    active = App.ActiveDocument.Name if App.ActiveDocument else None
    login = session.Session.client, session.Session.user
    parameters = drawing_bom_ui.settings._parameters
    get_text = ui.QtWidgets.QInputDialog.getText
    values, checks = {}, []
    dialog = None

    def check(label, result):
        assert result, label
        checks.append(label)

    try:
        drawing_bom_ui.settings._parameters = lambda: SimpleNamespace(
            GetString=lambda key, default: values.get(key, default),
            SetString=lambda key, value: values.update({key: value}),
        )
        document = App.newDocument("ForgePDMTitleAcceptance")
        page = document.addObject("TechDraw::DrawPage", "Page")
        template = document.addObject("TechDraw::DrawSVGTemplate", "Template")
        template_path = case / "template.svg"
        template_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="297mm" height="210mm" '
            'viewBox="0 0 297 210"><rect x="5" y="5" width="287" height="200" '
            'fill="none" stroke="black"/></svg>'
        )
        template.Template = str(template_path)
        page.Template = template
        document.recompute()
        report = {
            "item_number": "A000001",
            "revision_label": "A",
            "lines": [
                {
                    "component_revision_id": "fixture-part",
                    "position": 1,
                    "item_number": "P000001",
                    "revision_label": "A",
                    "quantity": "2",
                    "description": "Steel plate",
                }
            ],
        }
        legacy = copy.deepcopy(model.DEFAULT)
        legacy.pop("title")
        table = model.apply(document, page, None, report, legacy, {}, 140, 60)
        data = json.loads(table.PDMTableData)
        data["layout"].pop("title")
        table.PDMTableData = json.dumps(data)
        dialog = drawing_bom_ui.DrawingBOMDialog(None, report, [page], table)
        check("legacy table loads original title", dialog.title.text() == model.DEFAULT["title"])
        dialog.title.setText("Lista de peças — {item_number} Rev {revision_label}")
        ui.QtWidgets.QInputDialog.getText = lambda *args: ("Title acceptance", True)
        dialog.save_layout()
        saved = json.loads(values["DrawingBOMLayouts"])["Title acceptance"]
        dialog.title.clear()
        dialog.load_layout(saved)
        check("custom title survives preset save/load", dialog.title.text() == saved["title"])
        dialog.accept()
        check("native dialog accepts custom title", dialog.result() == 1)
        definition = dialog.definition()
        model.apply(document, page, table, report, definition, {}, 140, 60)
        check(
            "native SVG renders custom title without footer",
            "Lista de peças — A000001 Rev A" in table.Symbol
            and "Stored direct EBOM" not in table.Symbol
            and "CAD estimate" not in table.Symbol,
        )
        check("drawing stores title", model.read_table(table)["layout"]["title"] == saved["title"])
        updated = {**report, "revision_label": "B"}
        model.apply(document, page, table, updated, definition, {}, 140, 60)
        check("explicit update resolves revision placeholder", "A000001 Rev B" in table.Symbol)
        dialog.deleteLater()
        dialog = drawing_bom_ui.DrawingBOMDialog(None, updated, [page], table)
        check("update editor reloads saved title", dialog.title.text() == saved["title"])
        dialog.reject()
        dialog.deleteLater()
        dialog = None
        filename = case / "title.FCStd"
        document.recompute()
        document.saveAs(str(filename))
        App.closeDocument(document.Name)
        restored = App.openDocument(str(filename))
        restored_table = restored.getObject("ForgePDMBOM")
        check(
            "save/reopen retains title and footer removal",
            model.read_table(restored_table)["layout"]["title"] == saved["title"]
            and "Lista de peças" in restored_table.Symbol
            and "Stored direct EBOM" not in restored_table.Symbol,
        )
        pdf = case / "title.pdf"
        TechDrawGui.exportPageAsPdf(restored.getObject("Page"), str(pdf))
        check("native PDF export succeeds", pdf.is_file() and pdf.stat().st_size > 1000)
        blank_svg, _, blank_height = model.render(updated, {**definition, "title": ""}, {})
        _, _, title_height = model.render(updated, definition, {})
        check(
            "blank title hides title and removes reserved space",
            "Lista" not in blank_svg and blank_height < title_height,
        )
    finally:
        if dialog:
            dialog.reject()
            dialog.deleteLater()
        drawing_bom_ui.settings._parameters = parameters
        ui.QtWidgets.QInputDialog.getText = get_text
        for name in set(App.listDocuments()) - set(before):
            App.closeDocument(name)
        if active:
            App.setActiveDocument(active)
        check("open user documents, frozen tables and saved bytes preserved", documents() == before)
        check("session preserved", (session.Session.client, session.Session.user) == login)
    result = {
        "status": "passed",
        "checks": checks,
        "freecad": App.Version(),
        "qt": ui.QtCore.qVersion(),
        "scope": "Installed native model/dialog; synthetic disposable report, no server writes",
    }
    (case / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
