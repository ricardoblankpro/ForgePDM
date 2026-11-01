"""Live native-Assembly BOM smoke test; run only on an authorized test assembly.

Invoke run(App, Gui, [expected component numbers]) through MCP. The current BOM
must be empty. Actual dialogs select all direct links and approve replacement.
CAD files, placements, joints and the user's login are retained.
"""


def read_display(App, Gui):
    """Read and close the real Show BOM dialog without modifying the assembly."""
    from freecad.forgepdm import session, tasks, ui

    assert not session.Session.busy
    captured = []
    loop = ui.QtCore.QEventLoop()
    timer = ui.QtCore.QTimer()
    watchdog = ui.QtCore.QTimer()

    def observe():
        dialog = ui.QtWidgets.QApplication.activeModalWidget()
        if dialog and dialog.windowTitle().startswith("ForgePDM BOM"):
            captured.append(dialog.findChild(ui.QtWidgets.QPlainTextEdit).toPlainText())
            dialog.accept()
        if job.done and not session.Session.busy:
            timer.stop()
            ui.QtCore.QTimer.singleShot(350, loop.quit)

    timer.timeout.connect(observe)
    timer.start(10)
    watchdog.setSingleShot(True)
    watchdog.timeout.connect(loop.quit)
    watchdog.start(10000)
    Gui.runCommand("ForgePDM_ShowBOM", 0)
    job = tasks.active_job()
    assert job is not None
    loop.exec()
    timer.stop()
    watchdog.stop()
    assert job.done and job.error is None and len(captured) == 1
    return captured[0]


def run(App, Gui, expected_numbers, report_path="/tmp/forgepdm-native-bom-report.json"):
    from concurrent.futures import ThreadPoolExecutor
    import hashlib
    import importlib
    import json
    from pathlib import Path
    import sys

    import freecad.forgepdm as package
    from freecad.forgepdm import cad, commands, session, tasks, ui

    assert not session.Session.busy
    importlib.reload(package)
    importlib.reload(cad)
    client = session.Session.require_client()
    document = App.ActiveDocument
    assert document is not None
    metadata = document.getObject("ForgePDM_Metadata")
    revision_id = metadata.RevisionId
    assembly = next(obj for obj in document.Objects if obj.TypeId == "Assembly::AssemblyObject")
    report = {
        "freecad": App.Version(),
        "python": sys.version,
        "qt": ui.QtCore.qVersion(),
        "addon_version": package.__version__,
        "checks": [],
        "revision_id": revision_id,
        "scope": "User-authorized native Assembly with direct App::Links and a grounded joint; real UI/HTTP BOM synchronization",
    }
    executor = ThreadPoolExecutor(max_workers=1)

    def worker(function, *args):
        future = executor.submit(function, *args)
        loop = ui.QtCore.QEventLoop()
        timer = ui.QtCore.QTimer()
        timer.timeout.connect(lambda: loop.quit() if future.done() else None)
        timer.start(5)
        if not future.done():
            loop.exec()
        timer.stop()
        return future.result(timeout=1)

    def check(label, result):
        assert result, label
        report["checks"].append(label)

    def geometry_state():
        return {
            "placements": {
                obj.Name: str(obj.Placement)
                for obj in document.Objects
                if hasattr(obj, "Placement")
            },
            "members": [obj.Name for obj in assembly.Group],
            "grounded": {
                obj.Name: obj.ObjectToGround.Name
                for obj in document.Objects
                if hasattr(obj, "ObjectToGround")
            },
        }

    def hashes():
        return {
            doc.FileName: hashlib.sha256(Path(doc.FileName).read_bytes()).hexdigest()
            for doc in App.listDocuments().values()
            if doc.FileName
        }

    before_geometry, before_hashes = geometry_state(), hashes()
    before_bom = worker(client.get_bom, revision_id)
    assert not before_bom, "Existing engineering BOM must be reviewed manually before replacement"
    candidates = cad.capture_bom(document)
    check(
        "native assembly exposes exactly the expected component links",
        len(candidates) == len(expected_numbers),
    )
    check(
        "joint objects excluded from engineering occurrences",
        all(ref["object_name"] not in ("GroundedJoint", "Joints") for ref in candidates),
    )
    originals = []
    notifications = []
    for module in (commands, tasks):
        for name in ("information", "warning", "error"):
            if hasattr(module, name):
                originals.append((module, name, getattr(module, name)))
                setattr(
                    module,
                    name,
                    lambda title, message, kind=name: notifications.append((kind, message)),
                )
    phase = ["show"]
    loop = ui.QtCore.QEventLoop()
    timer = ui.QtCore.QTimer()
    watchdog = ui.QtCore.QTimer()
    callback_errors = []
    job = None

    def observe():
        try:
            dialog = ui.QtWidgets.QApplication.activeModalWidget()
            title = dialog.windowTitle() if dialog else ""
            if phase[0] == "show" and title.startswith("ForgePDM BOM"):
                button = next(
                    button
                    for button in dialog.findChildren(ui.QtWidgets.QPushButton)
                    if button.text().startswith("Synchronize from CAD")
                )
                phase[0] = "select"
                button.click()
            elif phase[0] == "select" and title == "Select engineering BOM occurrences":
                boxes = dialog.findChildren(ui.QtWidgets.QCheckBox)
                check(
                    "selection dialog lists component links only",
                    len(boxes) == len(expected_numbers),
                )
                check(
                    "selection labels show expected item numbers",
                    all(any(number in box.text() for box in boxes) for number in expected_numbers),
                )
                for box in boxes:
                    box.setChecked(True)
                phase[0] = "review"
                dialog.accept()
            elif phase[0] == "review" and title == "Review BOM replacement":
                consent = dialog.findChild(ui.QtWidgets.QCheckBox)
                buttons = dialog.findChild(ui.QtWidgets.QDialogButtonBox)
                check(
                    "BOM replacement requires explicit consent",
                    not buttons.button(ui.QtWidgets.QDialogButtonBox.Ok).isEnabled(),
                )
                consent.setChecked(True)
                phase[0] = "submitted"
                dialog.accept()
            if job is not None and job.done and not session.Session.busy:
                timer.stop()
                ui.QtCore.QTimer.singleShot(350, loop.quit)
        except BaseException as exception:
            callback_errors.append(exception)
            timer.stop()
            loop.quit()

    try:
        timer.timeout.connect(observe)
        timer.start(10)
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(loop.quit)
        watchdog.start(15000)
        Gui.runCommand("ForgePDM_ShowBOM", 0)
        job = tasks.active_job()
        assert job is not None
        loop.exec()
        timer.stop()
        watchdog.stop()
        if callback_errors:
            raise callback_errors[0]
        check("public Show BOM synchronization completed", job.done and not session.Session.busy)
        if job.error:
            raise job.error
        lines = worker(client.get_bom, revision_id)
        check(
            "engineering BOM contains expected components",
            sorted(line["item_number"] for line in lines) == sorted(expected_numbers),
        )
        check("each component quantity is one", all(line["quantity"] == "1" for line in lines))
        check(
            "exact pinned component revisions retained",
            {line["component_revision_id"] for line in lines}
            == {ref["target_revision_id"] for ref in candidates},
        )
        check(
            "Show BOM renders both component numbers",
            all(number in commands._format_bom(lines) for number in expected_numbers),
        )
        rendered = read_display(App, Gui)
        check(
            "reopened Show BOM dialog displays saved components",
            all(number in rendered for number in expected_numbers),
        )
        check(
            "placements, membership and grounded constraints preserved",
            geometry_state() == before_geometry,
        )
        check("all open native files retain their byte hashes", hashes() == before_hashes)
        check("original active assembly retained", App.ActiveDocument is document)
        toolbar = next(
            bar
            for bar in Gui.getMainWindow().findChildren(ui.QtWidgets.QToolBar)
            if bar.objectName() == "ForgePDM"
        )
        check(
            "toolbar actions reactivated after synchronization",
            all(action.isEnabled() for action in toolbar.actions()),
        )
        report.update(
            {
                "status": "passed",
                "lines": lines,
                "notifications": notifications,
                "rendered_text": rendered,
            }
        )
    except BaseException as exception:
        report.update({"status": "failed", "error": str(exception), "notifications": notifications})
        raise
    finally:
        timer.stop()
        watchdog.stop()
        for module, name, function in originals:
            setattr(module, name, function)
        executor.shutdown(wait=True)
        Path(report_path).write_text(json.dumps(report, indent=2) + "\n")
    return report
