"""Actual FreeCAD/HTTP round trips with original drawing templates unavailable."""


def run(App, Gui, directory):
    import importlib
    import json
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path
    from threading import get_ident
    from time import monotonic
    from zipfile import ZipFile

    import TechDrawGui
    import freecad.forgepdm as package

    previous_path = list(package.__path__)
    package.__path__ = [str(Path(__file__).parents[1] / "freecad/forgepdm")]
    from freecad.forgepdm import (
        api,
        cad,
        commands,
        fcstd,
        session,
        techdraw,
        tree_observer,
        ui,
        workspace,
    )

    for module in (techdraw, fcstd, workspace, cad, commands):
        importlib.reload(module)
    case = Path(directory)
    config = json.loads((case / "connection.json").read_text())
    original_session = session.Session.client, session.Session.user
    original_names = set(App.listDocuments())
    original_active = App.ActiveDocument.Name if App.ActiveDocument else None
    original_states = {
        d.Name: (d.Label, cad.document_modified(d)) for d in App.listDocuments().values()
    }
    original_files = {
        d.FileName: workspace.digest(d.FileName)[0]
        for d in App.listDocuments().values()
        if d.FileName
    }
    originals = {
        name: getattr(commands, name)
        for name in ("ask_choice", "_choose_workspace", "information", "warning")
    }
    import sys

    status_module = sys.modules.get("freecad.forgepdm.tree_status")
    status_controller = getattr(status_module, "_controller", None)
    if status_controller is not None:
        status_controller.timer.stop()
    executor = ThreadPoolExecutor(max_workers=1)
    report = dict(
        freecad=App.Version(),
        checks=[],
        scope="Disposable backend/workspaces; real upload, atomic check-in, configuration retrieval and TechDraw SVG export",
    )
    selected = {"kind": "part", "workspace": "working"}
    main_thread, threads = get_ident(), []

    def check(label, condition):
        assert condition, label
        report["checks"].append(label)

    def worker(function, *args, **kwargs):
        def execute():
            threads.append(get_ident())
            return function(*args, **kwargs)

        future = executor.submit(execute)
        loop, timer = ui.QtCore.QEventLoop(), ui.QtCore.QTimer()
        timer.timeout.connect(lambda: loop.quit() if future.done() else None)
        timer.start(5)
        if not future.done():
            loop.exec()
        timer.stop()
        return future.result()

    def drive(command):
        workflow, value, error = command.action(), None, None
        while True:
            try:
                request = workflow.throw(error) if error else workflow.send(value)
            except StopIteration:
                return
            try:
                value = worker(request.function, *request.args, **request.kwargs)
                error = None
            except BaseException as exception:
                error = exception

    def wait_projection(view):
        deadline = monotonic() + 10
        loop, timer = ui.QtCore.QEventLoop(), ui.QtCore.QTimer()
        timer.timeout.connect(
            lambda: loop.quit() if view.getVisibleEdges() or monotonic() > deadline else None
        )
        timer.start(10)
        if not view.getVisibleEdges():
            loop.exec()
        timer.stop()
        assert view.getVisibleEdges(), "Drawing projection did not complete"

    def page(document, source, suffix, title):
        template_path = case / ("template-" + suffix + ".svg")
        image = ui.QtGui.QImage(2, 2, ui.QtGui.QImage.Format_RGB32)
        image.fill(ui.QtGui.QColor("#2878c8"))
        image_buffer = ui.QtCore.QBuffer()
        image_buffer.open(ui.QtCore.QIODevice.WriteOnly)
        assert image.save(image_buffer, "PNG")
        encoded = bytes(image_buffer.data().toBase64()).decode()
        wrapped = "\n".join(encoded[start : start + 60] for start in range(0, len(encoded), 60))
        image_buffer.close()
        template_path.write_text(
            """<svg xmlns="http://www.w3.org/2000/svg" xmlns:freecad="http://www.freecadweb.org/wiki/index.php?title=Svg_Namespace" width="297mm" height="210mm" viewBox="0 0 297 210"><rect x="5" y="5" width="287" height="200" fill="none" stroke="black"/><text x="15" y="195" freecad:editable="Title"><tspan>Default</tspan></text></svg>""".replace(
                "</svg>",
                '<image xmlns:xlink="http://www.w3.org/1999/xlink" x="280" y="195" width="4" height="4" xlink:href="data:image/png;base64,'
                + wrapped
                + '"/></svg>',
            )
        )
        sheet = document.addObject("TechDraw::DrawPage", "Page" + suffix)
        template = document.addObject("TechDraw::DrawSVGTemplate", "Template" + suffix)
        template.Template = str(template_path)
        template.EditableTexts = {"Title": title}
        sheet.Template = template
        view = document.addObject("TechDraw::DrawViewPart", "Front" + suffix)
        view.Source = [source]
        view.Direction = (0, -1, 0)
        view.X, view.Y = 100, 110
        sheet.addView(view)
        document.recompute()
        wait_projection(view)
        dimension = document.addObject("TechDraw::DrawViewDimension", "Width" + suffix)
        dimension.Type = "Distance"
        dimension.References2D = [(view, ("Edge1",))]
        sheet.addView(dimension)
        dimension.X, dimension.Y = 100, 45
        note = document.addObject("TechDraw::DrawViewAnnotation", "Note" + suffix)
        note.Text = ["Manufacturing note"]
        sheet.addView(note)
        document.recompute()
        return sheet, template_path

    def retrieve(document, name):
        metadata = document.getObject("ForgePDM_Metadata")
        entry = workspace.binding(document.FileName, client.base_url)["entry"]
        configuration = worker(
            client.retrieve_configuration,
            str(case / name),
            metadata.RevisionId,
            entry["dataset_id"],
            entry["file_id"],
        )
        opened = cad.open_configuration(configuration, commands._set_metadata)
        worker(client.finish_configuration, configuration)
        return opened

    def verify_drawing(document, suffix, title, export_name):
        template, sheet = (
            document.getObject("Template" + suffix),
            document.getObject("Page" + suffix),
        )
        check(export_name + " editable title survives", template.EditableTexts["Title"] == title)
        check(export_name + " embedded template restored", Path(template.PageResult).is_file())
        dimension = document.getObject("Width" + suffix)
        wait_projection(document.getObject("Front" + suffix))
        check(export_name + " dimension survives", abs(dimension.getRawValue() - 100) < 1e-6)
        view = document.getObject("Front" + suffix)
        check(export_name + " drawing source stays local", view.Source[0].Document is document)
        export = case / (export_name + ".svg")
        TechDrawGui.exportPageAsSvg(sheet, str(export))
        from xml.etree import ElementTree as ET

        text = " ".join(ET.fromstring(export.read_bytes()).itertext())
        check(
            export_name + " embedded logo survives export",
            b"data:image/png;base64," in export.read_bytes(),
        )
        check(
            export_name + " page renders title and note",
            title in text and "Manufacturing note" in text,
        )

    client = api.ForgePDMClient(config["base_url"])
    try:
        user = worker(client.login, config["username"], config["password"])
        session.Session.set_client(client, user)
        commands.ask_choice = lambda title, prompt, choices, *args: (
            selected["kind"] if title == "New ForgePDM Item" else choices[0]
        )
        commands._choose_workspace = lambda *a: str(case / selected["workspace"])
        commands.information = commands.warning = lambda *a: None
        part = App.newDocument("TechDrawPartFixture")
        box = part.addObject("Part::Box", "Box")
        box.Length = box.Width = box.Height = 100
        _, part_svg = page(part, box, "Part", "Part approved")
        _, second_svg = page(part, box, "Detail", "Second page")
        part.saveAs(str(case / "part.FCStd"))
        drive(commands.UploadCommand())
        drive(commands.CheckInCommand())
        check("part with two TechDraw pages checks in cleanly", not cad.document_modified(part))
        with ZipFile(part.FileName) as archive:
            check(
                "both templates embedded in native snapshot",
                all(path.name in archive.namelist() for path in (part_svg, second_svg)),
            )
        for path in (part_svg, second_svg):
            path.rename(path.with_suffix(".unavailable"))
        check(
            "original part templates unavailable", not part_svg.exists() and not second_svg.exists()
        )
        downloaded = retrieve(part, "part-download")["root"]
        check(
            "restored part is clean before native SVG export", not cad.document_modified(downloaded)
        )
        verify_drawing(downloaded, "Part", "Part approved", "part-restored")
        verify_drawing(downloaded, "Detail", "Second page", "detail-restored")
        selected["workspace"] = "part-download"
        drive(commands.CheckoutCommand())
        downloaded.TemplatePart.EditableTexts = {"Title": "Edited after retrieval"}
        downloaded.recompute()
        drive(commands.CheckInCommand())
        check(
            "title field can be edited and checked in without original SVG",
            not cad.document_modified(downloaded),
        )
        reopened = retrieve(downloaded, "part-second-download")["root"]
        verify_drawing(reopened, "Part", "Edited after retrieval", "part-reedited")

        parent = App.newDocument("TechDrawAssemblyFixture")
        parent.saveAs(str(case / "assembly.FCStd"))
        assembly = parent.addObject("Assembly::AssemblyObject", "Assembly")
        link = parent.addObject("App::Link", "PartLink")
        link.setLink(downloaded.Box)
        assembly.addObject(link)
        sheet, assembly_svg = page(parent, link, "Assembly", "Assembly approved")
        assembly.addObject(sheet)
        parent.recompute()
        selected.update(kind="assembly", workspace="working")
        App.setActiveDocument(parent.Name)
        drive(commands.UploadCommand())
        refs = cad.capture_bom(parent)
        check(
            "TechDraw page inside native assembly is not a BOM component",
            [r["object_name"] for r in refs] == ["PartLink"],
        )
        drive(commands.CheckInCommand())
        entry = workspace.binding(parent.FileName, client.base_url)["entry"]
        manifest = worker(client.get_manifest, entry["dataset_id"])
        check(
            "assembly manifest contains only exact CAD occurrence",
            len(manifest["references"]) == 1
            and manifest["references"][0]["object_name"] == "PartLink",
        )
        original_pin = manifest["references"][0]["target_file_id"]
        assembly_svg.rename(assembly_svg.with_suffix(".unavailable"))
        opened = retrieve(parent, "assembly-download")
        restored = opened["root"]
        pins = worker(client.validate_references, cad.capture_bom(restored))
        check(
            "assembly download retains exact child pin", pins[0]["target_file_id"] == original_pin
        )
        check(
            "all reconstructed assembly documents are clean before native SVG export",
            all(not cad.document_modified(d) for d in opened["owned"]),
        )
        verify_drawing(restored, "Assembly", "Assembly approved", "assembly-restored")
        verify_drawing(
            restored.PartLink.LinkedObject.Document,
            "Part",
            "Edited after retrieval",
            "assembly-child-restored",
        )
        check(
            "template paths stayed unavailable throughout retrieval",
            not part_svg.exists() and not second_svg.exists() and not assembly_svg.exists(),
        )
        check("HTTP work executes off GUI thread", threads and main_thread not in threads)
        report["status"] = "passed"
    except BaseException as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        for name, function in originals.items():
            setattr(commands, name, function)
        for name in set(App.listDocuments()) - original_names:
            doc = App.getDocument(name)
            metadata = doc.getObject("ForgePDM_Metadata")
            if metadata:
                tree_observer.revoke_revision(metadata.RevisionId)
            App.closeDocument(name)
        session.Session.set_client(*original_session)
        package.__path__ = previous_path
        if original_active:
            App.setActiveDocument(original_active)
        if status_controller is not None:
            status_controller.timer.start()
        executor.shutdown(wait=True)
        check(
            "user documents and dirty states preserved",
            original_states
            == {d.Name: (d.Label, cad.document_modified(d)) for d in App.listDocuments().values()},
        )
        check(
            "user saved file bytes preserved",
            all(workspace.digest(p)[0] == value for p, value in original_files.items()),
        )
        (case / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
