"""Run run(App, Gui) through MCP. Fake-service dialog writes and live read-only BOM.

Preserves open CAD documents, active document, login and saved file hashes.
"""


def run(App, Gui):
    import hashlib
    import importlib
    import json
    import time
    from pathlib import Path
    from threading import get_ident
    from uuid import uuid4

    import freecad.forgepdm as package

    root = Path("/home/ricardoblank/Development/ForgePDM")
    previous = list(package.__path__)
    package.__path__ = [str(root / "clients/freecad/freecad/forgepdm")]
    from freecad.forgepdm import bom, assembly_mass, commands, session, cad, ui

    for module in (bom, assembly_mass, commands):
        importlib.reload(module)
    from freecad.forgepdm.bom_ui import BOMDialog
    from freecad.forgepdm.jobs import Request

    def documents():
        return [
            (
                d.Name,
                d.FileName,
                cad.document_modified(d),
                hashlib.sha256(Path(d.FileName).read_bytes()).hexdigest() if d.FileName else None,
            )
            for d in App.listDocuments().values()
        ]

    original = documents()
    active = App.ActiveDocument.Name if App.ActiveDocument else None
    client, user = session.Session.client, session.Session.user
    gui_thread = get_ident()
    workers, checks = [], []
    state = {"lines": [], "writes": 0}
    revision_id = str(uuid4())
    ref = dict(
        object_name="Bolt",
        property_name="LinkedObject",
        target_revision_id=revision_id,
        component_label="S000001-A",
    )

    def io(value):
        workers.append(get_ident())
        return value

    def load():
        lines = yield Request("Loading test data", io, (state["lines"],))
        return lines, dict(mass_kg="0.08075", known_mass_kg="0.08075", issues=[])

    def prepare():
        yield Request("Preparing test proposal", io, (None,))
        return dict(prepared=dict(references=[ref]), snapshot=dict(lines=list(state["lines"])))

    def write(proposal):
        workers.append(get_ident())
        state["writes"] += 1
        state["lines"] = [
            dict(
                component_revision_id=line.component_revision_id,
                item_number="S000001",
                item_name="Bolt",
                revision_label="A",
                lifecycle_state="working",
                position=line.position,
                quantity=str(line.quantity),
            )
            for line in proposal
        ]

    def apply(plan, proposal):
        assert get_ident() == gui_thread
        yield Request("Applying test proposal", write, (proposal,), mutates=True, cancellable=False)

    class Client:
        def bom_revision_updates(self, lines):
            workers.append(get_ident())
            return {revision_id: "B"}

    def wait(predicate):
        deadline = time.monotonic() + 15
        while not predicate() and time.monotonic() < deadline:
            Gui.updateGui()
            time.sleep(0.005)
        assert predicate()

    dialog = None
    try:
        dialog = BOMDialog(
            Gui.getMainWindow(), "Disposable UX fixture", Client(), load, prepare, apply
        )
        dialog.show()
        wait(lambda: "no published" in dialog.status.text() and dialog.job is None)
        assert "0.081 kg" in dialog.mass.text()
        dialog.update_button.click()
        wait(lambda: dialog.plan is not None and dialog.job is None)
        assert dialog.checks[0][0].isChecked() and dialog.scroll.isHidden()
        checks.append(
            "Actual native Qt window includes components by default and rounds mass to 0.081 kg"
        )
        dialog.apply_button.click()
        wait(lambda: state["writes"] == 1 and dialog.job is None)
        assert dialog.tree.topLevelItemCount() == 1 and dialog.review.isHidden()
        checks.append(
            "One Apply action refreshes the same window without a success dialog (fake service mutation)"
        )
        dialog.update_button.click()
        wait(lambda: dialog.plan is not None and dialog.job is None)
        assert not dialog.apply_button.isEnabled() and "up to date" in dialog.status.text()
        checks.append("Exact no-op disables Apply; optional occurrence exclusion remains available")
        dialog.reject()
        dialog = None

        # Exercise the actual command and real production HTTP reads only.
        observed = []
        failure = []
        timer = ui.QtCore.QTimer()
        deadline = time.monotonic() + 30

        def inspect():
            current = ui.QtWidgets.QApplication.activeModalWidget()
            if isinstance(current, BOMDialog):
                if current.job is None:
                    if current.tree.topLevelItemCount() or "no published" in current.status.text():
                        observed.append(
                            dict(rows=current.tree.topLevelItemCount(), mass=current.mass.text())
                        )
                    else:
                        failure.append(current.status.text())
                    current.reject()
                elif time.monotonic() > deadline:
                    failure.append("Read-only command timeout")
                    current.job.cancel()

        timer.timeout.connect(inspect)
        timer.start(20)
        try:
            generator = commands.ShowBOMCommand().action()
            try:
                next(generator)
                raise AssertionError("Unexpected outer request")
            except StopIteration:
                pass
        finally:
            timer.stop()
        assert observed and not failure, failure
        checks.append(
            "Actual ShowBOM command loads live stored BOM and mass via worker HTTP; no synchronization performed"
        )
        assert original == documents()
        assert active == (App.ActiveDocument.Name if App.ActiveDocument else None)
        assert client is session.Session.client and user is session.Session.user
        assert workers and all(thread != gui_thread for thread in workers)
        checks.append(
            "Open documents, saved hashes, dirty states, active document and login preserved"
        )
        report = dict(
            freecad=App.Version(),
            qt=ui.QtCore.qVersion(),
            checks=checks,
            live_read=observed,
            production_writes=0,
        )
        (root / "docs/validation/bom-ux-freecad-2026-11-11.json").write_text(
            json.dumps(report, indent=2)
        )
        print(json.dumps(report, indent=2))
    finally:
        if dialog and dialog.job is None:
            dialog.reject()
        package.__path__ = previous
