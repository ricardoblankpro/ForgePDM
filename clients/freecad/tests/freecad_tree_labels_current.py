"""Apply tested labels to an explicitly authorized, clean uploaded working assembly.

Runs the real refresh and upload commands. Makes a native-file backup first;
preserves geometry, internal names, dependencies, component files and BOM lines.
"""


def run(App, Gui, report_path="/tmp/forgepdm-tree-labels-current.json"):
    from concurrent.futures import ThreadPoolExecutor
    import hashlib
    import json
    from pathlib import Path
    import shutil
    import tempfile

    from freecad.forgepdm import commands, session, tasks, tree_labels, ui, workspace

    assert not session.Session.busy
    document = App.ActiveDocument
    client = session.Session.require_client()
    metadata = document.getObject("ForgePDM_Metadata")
    entry = workspace.binding(document.FileName, client.base_url)["entry"]
    assert not Gui.getDocument(document.Name).Modified and not document.HasPendingTransaction
    assert workspace.digest(document.FileName)[0] == entry["working_hash"], (
        "Upload existing CAD changes explicitly first"
    )
    backup = Path(tempfile.mkdtemp(prefix="forgepdm-before-tree-labels-")) / "assembly.FCStd"
    shutil.copy2(document.FileName, backup)
    executor = ThreadPoolExecutor(max_workers=1)
    report = {
        "checks": [],
        "scope": "Authorized current uploaded working assembly; actual refresh and upload toolbar commands",
    }

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

    def state():
        links = [obj for obj in document.Objects if obj.TypeId == "App::Link"]
        return {
            "links": [
                (
                    obj.Name,
                    obj.LinkedObject.Name,
                    obj.LinkedObject.Document.getObject("ForgePDM_Metadata").RevisionId,
                    str(obj.Placement),
                    obj.Shape.Volume,
                )
                for obj in links
            ],
            "grounding": [
                (obj.Name, obj.ObjectToGround.Name)
                for obj in document.Objects
                if hasattr(obj, "ObjectToGround")
            ],
        }

    before = state()
    children = {
        obj.LinkedObject.Document.FileName for obj in document.Objects if obj.TypeId == "App::Link"
    }
    child_hashes = {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in children}
    before_bom = worker(client.get_bom, metadata.RevisionId)
    originals, notifications = [], []
    for module in (commands, tasks):
        for name in ("information", "warning", "error"):
            if hasattr(module, name):
                originals.append((module, name, getattr(module, name)))
                setattr(
                    module,
                    name,
                    lambda title, message, kind=name: notifications.append((kind, message)),
                )

    def invoke(name):
        Gui.runCommand(name, 0)
        job = tasks.active_job()
        assert job is not None
        loop = ui.QtCore.QEventLoop()
        timer = ui.QtCore.QTimer()
        timer.timeout.connect(
            lambda: loop.quit() if job.done and not session.Session.busy else None
        )
        timer.start(10)
        watchdog = ui.QtCore.QTimer()
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(loop.quit)
        watchdog.start(20000)
        loop.exec()
        timer.stop()
        watchdog.stop()
        assert job.done and not session.Session.busy
        if job.error:
            raise job.error

    def check(label, result):
        assert result, label
        report["checks"].append(label)

    try:
        invoke("ForgePDM_RefreshTreeLabels")
        rows = [
            (obj.Name, obj.Label, obj.ForgePDMOccurrenceId, obj.ForgePDMOccurrenceNumber)
            for obj in document.Objects
            if obj.TypeId == "App::Link"
        ]
        check(
            "current tree shows expected pinned item/revision occurrences",
            {row[1] for row in rows}
            == {"P000004-B|1", "P000005-A|1", "P000005-A|2", "P000006-A|1"},
        )
        check("current occurrences have distinct UUIDs", len({row[2] for row in rows}) == len(rows))
        invoke("ForgePDM_Upload")
        check(
            "label metadata and allocation registry uploaded cleanly",
            workspace.digest(document.FileName)[0]
            == workspace.binding(document.FileName, client.base_url)["entry"]["working_hash"]
            and not Gui.getDocument(document.Name).Modified,
        )
        check(
            "names, linked revisions, shapes, placements and grounding unchanged", state() == before
        )
        check(
            "linked component file bytes unchanged",
            all(
                hashlib.sha256(Path(path).read_bytes()).hexdigest() == value
                for path, value in child_hashes.items()
            ),
        )
        check(
            "engineering BOM lines and quantities unchanged",
            worker(client.get_bom, metadata.RevisionId) == before_bom,
        )
        check(
            "second tree refresh makes no edits",
            not tree_labels.refresh(document)["changed"]
            and not Gui.getDocument(document.Name).Modified,
        )
        report.update(
            {
                "status": "passed",
                "labels": rows,
                "backup": str(backup),
                "notifications": notifications,
            }
        )
    except BaseException as error:
        report.update({"status": "failed", "error": str(error), "notifications": notifications})
        raise
    finally:
        for module, name, function in originals:
            setattr(module, name, function)
        executor.shutdown(wait=True)
        Path(report_path).write_text(json.dumps(report, indent=2) + "\n")
    return report
