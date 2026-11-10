"""Run run(App, Gui, case_directory) through MCP against a disposable backend.

connection.json supplies base_url, username, password, revision_id and number;
the fixture must have a nested assembly totaling 0.08075 kg.
"""


def run(App, Gui, case_directory):
    import importlib
    import json
    from pathlib import Path
    from concurrent.futures import ThreadPoolExecutor
    from decimal import Decimal
    import freecad.forgepdm as pkg

    old_path = list(pkg.__path__)
    pkg.__path__ = [str(Path(__file__).resolve().parents[1] / "freecad/forgepdm")]
    from freecad.forgepdm import api, commands, session, ui

    for mod in (api, commands):
        importlib.reload(mod)
    config = json.loads((Path(case_directory) / "connection.json").read_text())
    client = api.ForgePDMClient(config["base_url"])
    original = (session.Session.client, session.Session.user)
    doc = None
    checks = []
    executor = ThreadPoolExecutor(max_workers=1)

    def worker(fn, *args, **kwargs):
        future = executor.submit(fn, *args, **kwargs)
        loop = ui.QtCore.QEventLoop()
        timer = ui.QtCore.QTimer()
        timer.timeout.connect(lambda: loop.quit() if future.done() else None)
        timer.start(5)
        if not future.done():
            loop.exec()
        timer.stop()
        return future.result()

    try:
        user = worker(client.login, config["username"], config["password"])
        session.Session.client = client
        session.Session.user = user
        mass = worker(client.get_assembly_mass, config["revision_id"])
        assert Decimal(mass["mass_kg"]) == Decimal("0.08075")
        checks.append("Real HTTP client returns exact nested total 0.08075 kg")
        doc = App.newDocument("AssemblyMassValidation")
        commands._set_metadata(
            doc,
            ItemId="validation-item",
            RevisionId=config["revision_id"],
            ItemNumber=config["number"],
            RevisionLabel="A",
            ServerUrl=client.base_url,
        )

        def inspect():
            dialog = ui.QtWidgets.QApplication.activeModalWidget()
            if dialog and dialog.windowTitle().startswith("ForgePDM BOM"):
                texts = [w.text() for w in dialog.findChildren(ui.QtWidgets.QLabel)]
                if any("0.08075 kg" in s and "Stored engineering BOM" in s for s in texts):
                    checks.append("Actual Show BOM dialog displays total and published-data basis")
                dialog.accept()

        timer = ui.QtCore.QTimer()
        timer.timeout.connect(inspect)
        timer.start(20)
        generator = commands.ShowBOMCommand().action()
        value = None
        try:
            while True:
                request = generator.send(value)
                value = worker(request.function, *request.args, **request.kwargs)
        except StopIteration:
            pass
        finally:
            timer.stop()
        assert len(checks) == 2, checks
        report = {
            "freecad": App.Version(),
            "checks": checks,
            "mass_kg": mass["mass_kg"],
            "production_data_modified": False,
        }
        (Path(case_directory) / "native-report.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report))
    finally:
        if doc:
            App.closeDocument(doc.Name)
        session.Session.client, session.Session.user = original
        pkg.__path__ = old_path
        executor.shutdown()
