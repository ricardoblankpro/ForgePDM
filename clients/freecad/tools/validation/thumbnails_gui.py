"""Native isometric rendering and authorized selected-snapshot browser acceptance."""


def run(App, Gui, directory):
    import json
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path
    from uuid import uuid4

    import freecad.forgepdm as package
    from freecad.forgepdm import api, cad, commands, thumbnail_render, ui, workspace
    from freecad.forgepdm.open_ui import OpenDialog

    case = Path(directory)
    report = {"addon": package.__version__, "freecad": App.Version(), "checks": []}
    original_documents = set(App.listDocuments())
    active = App.ActiveDocument.Name if App.ActiveDocument else None
    original_selection = [
        (s.DocumentName, s.ObjectName, tuple(s.SubElementNames))
        for s in Gui.Selection.getSelectionEx()
    ]
    executor, dialog = ThreadPoolExecutor(max_workers=1), None

    def check(label, value):
        assert value, label
        report["checks"].append(label)

    def wait(predicate, timeout=10):
        import time

        loop, timer = ui.QtCore.QEventLoop(), ui.QtCore.QTimer()
        deadline = time.monotonic() + timeout
        timer.timeout.connect(
            lambda: loop.quit() if predicate() or time.monotonic() > deadline else None
        )
        timer.start(10)
        if not predicate():
            loop.exec()
        timer.stop()
        assert predicate(), "native preview acceptance timed out"

    def worker(function, *args):
        future = executor.submit(function, *args)
        wait(future.done)
        return future.result()

    try:
        document = App.newDocument("IsometricPreviewFixture")
        box = document.addObject("Part::Box", "Box")
        box.Length, box.Width, box.Height = 30, 20, 10
        hidden = document.addObject("Part::Box", "Hidden")
        hidden.ViewObject.Visibility = False
        document.recompute()
        document.saveAs(str(case / "preview-source.FCStd"))
        commands._save_document(document)
        view = Gui.getDocument(document.Name).activeView()
        view.setAnimationEnabled(False)
        view.viewTop()
        view.fitAll()
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(document.Name, box.Name, "Face1")
        before = (
            view.getCamera(),
            workspace.digest(document.FileName),
            cad.document_modified(document),
            [(obj.Name, obj.ViewObject.Visibility) for obj in document.Objects],
            [
                (s.DocumentName, s.ObjectName, tuple(s.SubElementNames))
                for s in Gui.Selection.getSelectionEx()
            ],
        )
        first = thumbnail_render.capture(document)
        after = (
            view.getCamera(),
            workspace.digest(document.FileName),
            cad.document_modified(document),
            [(obj.Name, obj.ViewObject.Visibility) for obj in document.Objects],
            [
                (s.DocumentName, s.ObjectName, tuple(s.SubElementNames))
                for s in Gui.Selection.getSelectionEx()
            ],
        )
        check(
            "camera, saved bytes, dirty state, visibility and subelement selection preserved",
            before == after,
        )
        check("animation setting preserved", not view.isAnimationEnabled())
        view.viewFront()
        second = thumbnail_render.capture(document)
        a, b = ui.QtGui.QImage(), ui.QtGui.QImage()
        a.loadFromData(first["png"], "PNG")
        b.loadFromData(second["png"], "PNG")
        check("different starting views produce the same isometric pixels", a == b)
        check("preview is exactly 384 by 384", a.width() == a.height() == 384)
        check(
            "preview source hash is the exact saved file",
            first["source_content_hash"] == workspace.digest(document.FileName)[0],
        )
        view.setCameraType("Perspective")
        view.viewRear()
        view.fitAll()
        perspective = view.getCamera()
        thumbnail_render.capture(document)
        check(
            "perspective camera type and full camera state are restored",
            view.getCameraType() == "Perspective" and view.getCamera() == perspective,
        )
        other = App.newDocument("PreviewActiveDocumentFixture")
        previous_camera = view.getCamera()
        thumbnail_render.capture(document)
        check(
            "capturing another document preserves the active document and camera",
            App.ActiveDocument is other and view.getCamera() == previous_camera,
        )
        App.setActiveDocument(document.Name)
        box.Length = 40
        document.recompute()
        check(
            "newer unsaved geometry is never represented as a saved snapshot",
            thumbnail_render.optional(document) is None
            and workspace.digest(document.FileName) == before[1],
        )
        commands._save_document(document)
        commands._set_metadata(
            document,
            ItemId=str(uuid4()),
            RevisionId=str(uuid4()),
            ItemNumber="P-QA",
            RevisionLabel="A",
            ServerUrl="http://preview.invalid",
        )
        commands._save_document(document)
        parent = App.newDocument("PreviewLinkedAssemblyFixture")
        parent.saveAs(str(case / "preview-parent.FCStd"))
        link = parent.addObject("App::Link", "Component")
        link.setLink(box)
        parent.recompute()
        parent.saveAs(str(case / "preview-parent.FCStd"))
        commands._save_document(parent)
        box.Width = 25
        document.recompute()
        check(
            "unsaved linked-component geometry also prevents a misleading parent preview",
            thumbnail_render.optional(parent) is None,
        )

        config = json.loads((case / "connection.json").read_text())
        client = api.ForgePDMClient(config["base_url"])
        worker(client.login, config["username"], config["password"])
        dialog = OpenDialog(None, client, str(case / "working"), lambda: str(case / "working"))
        dialog.show()
        dialog.query.setText("P000001")
        wait(
            lambda: (
                dialog.open_button.isEnabled()
                and dialog.preview.pixmap() is not None
                and not dialog.preview.pixmap().isNull()
            )
        )
        check(
            "native browser loads an authorized preview without opening CAD",
            len(App.listDocuments()) == len(original_documents) + 3,
        )
        check("native browser offers historical snapshots", dialog.snapshot.count() > 1)
        dialog.snapshot.setCurrentIndex(1)
        wait(lambda: not dialog.jobs)
        check(
            "changing snapshot refreshes preview while keeping Open available",
            dialog.open_button.isEnabled()
            and dialog.preview.pixmap() is not None
            and not dialog.preview.pixmap().isNull(),
        )
        dialog.grab().save(str(case / "native-preview.png"))
        dialog.pause(clear=True)
        check(
            "clearing the browser removes protected image pixels",
            dialog.preview.pixmap() is None or dialog.preview.pixmap().isNull(),
        )
        report["status"] = "passed"
    except BaseException as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        if dialog is not None:
            dialog.finish(0)
            wait(lambda: not dialog.jobs)
            dialog.deleteLater()
        executor.shutdown(wait=True)
        for name in set(App.listDocuments()) - original_documents:
            App.closeDocument(name)
        if active:
            App.setActiveDocument(active)
        Gui.Selection.clearSelection()
        for doc, obj, subelements in original_selection:
            for subelement in subelements or ("",):
                Gui.Selection.addSelection(doc, obj, subelement)
        (case / "preview-report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
