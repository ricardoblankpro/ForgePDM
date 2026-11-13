"""Disposable live Drawing BOM command, frozen uploads, retrieval and PDF acceptance."""


def run(App, Gui, directory):
    import hashlib
    import importlib.util
    import json
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path

    import TechDrawGui
    from freecad.forgepdm import (
        api,
        browser_panel,
        cad,
        commands,
        drawing_bom,
        session,
        settings,
        tree_observer,
        ui,
        workspace,
    )

    case = Path(directory)
    original_session = session.Session.client, session.Session.user
    original_active = App.ActiveDocument.Name if App.ActiveDocument else None

    def documents():
        return {
            d.Name: (
                d.FileName,
                cad.document_modified(d),
                hashlib.sha256(Path(d.FileName).read_bytes()).hexdigest() if d.FileName else None,
            )
            for d in App.listDocuments().values()
        }

    before = documents()
    panel_state = None
    if browser_panel._dock and browser_panel._dock.isVisible():
        view = browser_panel._dock.view
        panel_state = (view.source.currentIndex(), view.query.text())
    previous_layouts = settings._parameters().GetString("DrawingBOMLayouts", "")
    spec = importlib.util.spec_from_file_location(
        "drawing_seed", Path(__file__).parents[2] / "tests/freecad_atomic_checkin_integration.py"
    )
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    seed.run(App, Gui, str(case))
    config = json.loads((case / "connection.json").read_text())
    executor = ThreadPoolExecutor(max_workers=1)
    checks = []
    report = {
        "checks": checks,
        "freecad": App.Version(),
        "qt": ui.QtCore.qVersion(),
        "scope": "Disposable live HTTP/native CAD; actual Drawing BOM dialog and command; original documents preserved",
    }
    original_dialog = commands.execute_dialog
    client = api.ForgePDMClient(config["base_url"])

    def worker(function, *args, **kwargs):
        future = executor.submit(function, *args, **kwargs)
        loop = ui.QtCore.QEventLoop()
        timer = ui.QtCore.QTimer()
        timer.timeout.connect(lambda: loop.quit() if future.done() else None)
        timer.start(5)
        if not future.done():
            loop.exec()
        timer.stop()
        return future.result()

    def drive(workflow):
        value = None
        while True:
            try:
                request = workflow.send(value)
            except StopIteration:
                return
            value = worker(request.function, *request.args, **request.kwargs)

    def check(label, value):
        assert value, label
        checks.append(label)

    try:
        user = worker(client.login, config["username"], config["password"])
        session.Session.set_client(client, user)
        item = worker(client.search_items, "", number_series="A")["items"][0]
        parts = worker(client.search_items, "", number_series="P")["items"][:2]
        rid = item["current_revision_id"]
        worker(client.acquire_checkout, rid)
        lines = [
            {
                "component_revision_id": part["current_revision_id"],
                "quantity": str(index + 2),
                "position": 5 + index * 4,
            }
            for index, part in enumerate(parts)
        ]
        worker(client._json_request, "PUT", f"/api/v1/revisions/{rid}/bom", {"lines": lines})
        dataset = worker(client.list_datasets, rid)[-1]
        root = case / "drawing-workspace"
        root.mkdir(exist_ok=True)
        configuration = worker(
            client.retrieve_configuration, str(root), rid, dataset["id"], dataset["files"][0]["id"]
        )
        opened = cad.open_configuration(configuration, commands._set_metadata)
        worker(client.finish_configuration, configuration)
        document = opened["root"]
        drive(commands._ensure_working(client, document))
        page = document.addObject("TechDraw::DrawPage", "BOMPage")
        template = document.addObject("TechDraw::DrawSVGTemplate", "BOMTemplate")
        template_path = case / "drawing-template.svg"
        template_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="297mm" height="210mm" viewBox="0 0 297 210"><rect x="5" y="5" width="287" height="200" fill="none" stroke="black" stroke-width="0.5"/></svg>'
        )
        template.Template = str(template_path)
        page.Template = template
        document.recompute()
        mode = {"new": True, "renew": False}

        def configure(dialog):
            def accept():
                if mode["new"]:
                    dialog.add_column()
                    dialog.columns.item(5, 1).setText("Finish")
                    dialog.preview()
                    dialog.grid.item(0, 5).setText("PAINT BLUE")
                dialog.accept()

            ui.QtCore.QTimer.singleShot(20, accept)
            result = original_dialog(dialog)
            if mode["renew"]:
                worker(client.renew_checkout, rid)
            return result

        commands.execute_dialog = configure
        drive(commands.DrawingBOMCommand().action())
        target = next(obj for obj in document.Objects if hasattr(obj, "PDMTableData"))
        stored = drawing_bom.read_table(target)
        check(
            "native command inserts direct stored EBOM at exact positions",
            [line["position"] for line in stored["report"]["lines"]] == [5, 9],
        )
        check(
            "custom text is stored and rendered",
            "PAINT BLUE" in target.Symbol
            and any("PAINT BLUE" in note.values() for note in stored["notes"].values()),
        )
        target.X = 120
        target.Y = 95
        mode["new"] = False
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(target)
        lines[0]["quantity"] = "4"
        worker(client._json_request, "PUT", f"/api/v1/revisions/{rid}/bom", {"lines": lines})
        check(
            "server changes do not silently rewrite the drawing",
            drawing_bom.read_table(target)["report"]["lines"][0]["quantity"] == "2",
        )
        drive(commands.DrawingBOMCommand().action())
        updated = drawing_bom.read_table(target)
        check(
            "explicit update refreshes quantities and keeps custom text",
            updated["report"]["lines"][0]["quantity"] == "4"
            and updated["notes"] == stored["notes"],
        )
        check(
            "update preserves placement and column layout",
            float(target.X) == 120
            and float(target.Y) == 95
            and updated["layout"] == stored["layout"],
        )
        old = target.PDMTableData
        mode["renew"] = True
        try:
            drive(commands.DrawingBOMCommand().action())
        except workspace.WorkspaceError as error:
            check(
                "checkout renewal during review rejects local mutation",
                "Checkout changed" in str(error) and target.PDMTableData == old,
            )
        else:
            raise AssertionError("stale checkout accepted")
        mode["renew"] = False
        commands._save_document(document)
        references = cad.capture(document)
        published = worker(client.upload_native, document.FileName, rid, item["id"], references)
        check(
            "managed upload accepts embedded table and exact CAD pins",
            not published.get("local_changes_remain"),
        )
        template_path.rename(case / "template-original-unavailable.svg")
        lines[0]["quantity"] = "8"
        worker(client._json_request, "PUT", f"/api/v1/revisions/{rid}/bom", {"lines": lines})
        retrieved = worker(
            client.retrieve_configuration,
            str(root),
            rid,
            published["id"],
            published["files"][0]["id"],
        )
        copies = cad.open_configuration(retrieved, commands._set_metadata)
        worker(client.finish_configuration, retrieved)
        restored = copies["root"].getObject(target.Name)
        check(
            "retrieval retains frozen values after server changes",
            drawing_bom.read_table(restored)["report"]["lines"][0]["quantity"] == "4",
        )
        check(
            "offline restoration keeps columns and row text without original template",
            drawing_bom.read_table(restored)["layout"] == stored["layout"]
            and "PAINT BLUE" in restored.Symbol,
        )
        pdf = case / "drawing-bom.pdf"
        TechDrawGui.exportPageAsPdf(copies["root"].getObject(page.Name), str(pdf))
        check("restored table exports to PDF", pdf.is_file() and pdf.stat().st_size > 1000)
        check(
            "generation never rewrites stored EBOM quantities",
            worker(client.get_bom, rid)[0]["quantity"] == "8",
        )
        report["status"] = "passed"
    except BaseException as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        commands.execute_dialog = original_dialog
        Gui.Selection.clearSelection()
        for name in set(App.listDocuments()) - set(before):
            doc = App.getDocument(name)
            meta = doc.getObject("ForgePDM_Metadata")
            if meta:
                tree_observer.revoke_revision(meta.RevisionId)
            App.closeDocument(name)
        settings._parameters().SetString("DrawingBOMLayouts", previous_layouts)
        session.Session.set_client(*original_session)
        if original_active:
            App.setActiveDocument(original_active)
        if panel_state and original_session[0]:
            drive(commands.DownloadCommand().action())
            browser_panel._dock.view.source.setCurrentIndex(panel_state[0])
            browser_panel._dock.view.query.setText(panel_state[1])
        executor.shutdown(wait=True)
        report["original_documents_preserved"] = before == documents()
        report["original_document_count"] = len(before)
        (case / "drawing-report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
