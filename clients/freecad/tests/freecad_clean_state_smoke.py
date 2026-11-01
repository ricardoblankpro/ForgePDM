"""Read-only live backend regression: retrieve a temporary clone of the active CAD.

Invoke run(App, Gui). Existing documents/files/BOMs stay unchanged. A label edit
is injected only into a disposable downloaded component to verify dirty blocking.
"""


def run(App, Gui, report_path="/tmp/forgepdm-clean-state-report.json"):
    from concurrent.futures import ThreadPoolExecutor
    import hashlib
    import importlib
    import json
    from pathlib import Path
    import sys
    import tempfile

    import freecad.forgepdm as package
    from freecad.forgepdm import cad, commands, session, ui, workspace

    assert not session.Session.busy
    importlib.reload(package)
    importlib.reload(cad)
    client = session.Session.require_client()
    active = App.ActiveDocument
    before = {
        name: (
            doc.FileName,
            Gui.getDocument(name).Modified,
            hashlib.sha256(Path(doc.FileName).read_bytes()).hexdigest(),
        )
        for name, doc in App.listDocuments().items()
        if doc.FileName
    }
    source = workspace.binding(active.FileName, client.base_url)["entry"]
    directory = tempfile.mkdtemp(prefix="forgepdm-clean-state-")
    report = {
        "freecad": App.Version(),
        "python": sys.version,
        "qt": ui.QtCore.qVersion(),
        "addon_version": package.__version__,
        "checks": [],
        "scope": "Temporary verified clone of current assembly; read-only HTTP; dirty edit injected into disposable clone only",
    }
    executor = ThreadPoolExecutor(max_workers=1)
    opened = None

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

    try:
        configuration = worker(
            client.retrieve_configuration,
            directory,
            source["revision_id"],
            source["dataset_id"],
            source["file_id"],
        )
        opened = cad.open_configuration(configuration, commands._set_metadata)
        worker(client.finish_configuration, configuration)
        root = opened["root"]
        check(
            "retrieved root and components are not falsely modified",
            all(not cad.document_modified(doc) for doc in opened["owned"]),
        )
        references = cad.capture_bom(root)
        prepared = worker(client.prepare_cad_bom, root.FileName, source["revision_id"], references)
        check(
            "clean downloaded components pass complete pinned-snapshot verification",
            len(prepared["references"]) == len(references) == 3,
        )
        snapshot = worker(client.bom_snapshot, source["revision_id"])
        check("assembly checkout permits BOM editing", bool(snapshot["checkout_id"]))
        report["components"] = [ref["component_label"] for ref in prepared["references"]]

        dirty = root.getObject(references[0]["object_name"]).LinkedObject.Document
        number = dirty.getObject("ForgePDM_Metadata").ItemNumber
        dirty.Label += " — disposable dirty-state test"
        dirty.recompute()
        check("real edit stays modified after recompute", cad.document_modified(dirty))
        try:
            cad.capture_bom(root)
        except workspace.WorkspaceError as error:
            check(
                "real unsaved edit is rejected with affected component identity",
                number in str(error),
            )
        else:
            raise AssertionError("Unsaved component edit was accepted")
        retained = cad.close_owned(opened["owned"])
        check(
            "failed cleanup retains genuinely modified document",
            dirty.Name in retained and App.getDocument(dirty.Name) is dirty,
        )
        # Discard only the known test label edit in our disposable component.
        App.closeDocument(dirty.Name)
        opened = None
        check(
            "original documents and modification flags are unchanged",
            all(
                App.getDocument(name).FileName == values[0]
                and Gui.getDocument(name).Modified == values[1]
                and hashlib.sha256(Path(values[0]).read_bytes()).hexdigest() == values[2]
                for name, values in before.items()
            ),
        )
        report["status"] = "passed"
    except BaseException as error:
        report.update({"status": "failed", "error": str(error)})
        raise
    finally:
        if opened:
            for doc in reversed(opened["owned"]):
                if App.getDocument(doc.Name) is doc:
                    App.closeDocument(doc.Name)
        App.setActiveDocument(active.Name)
        executor.shutdown(wait=True)
        Path(report_path).write_text(json.dumps(report, indent=2) + "\n")
    return report
