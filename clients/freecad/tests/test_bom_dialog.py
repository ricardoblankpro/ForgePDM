"""Real Qt acceptance with fake service responses; run with --with PySide6.

This verifies the dialog/event loop, not native CAD extraction or live HTTP.
"""

import os
import time
from copy import deepcopy
from threading import get_ident
from uuid import uuid4

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from freecad.forgepdm.bom_ui import BOMDialog  # noqa: E402
from freecad.forgepdm.jobs import Request  # noqa: E402
from freecad.forgepdm.ui import QtWidgets  # noqa: E402


@pytest.fixture
def case():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    key = str(uuid4())
    main_thread = get_ident()
    state = dict(lines=[], writes=0, fail=False)
    threads = []
    ref = dict(
        object_name="Bolt",
        property_name="LinkedObject",
        target_revision_id=key,
        component_label="S000001-A",
    )
    mass = dict(mass_kg="0.08075", known_mass_kg="0.08075", issues=[])

    def request_result(result):
        threads.append(get_ident())
        return deepcopy(result)

    def load():
        lines = yield Request("Loading", request_result, (state["lines"],))
        return lines, mass

    def prepare():
        assert get_ident() == main_thread
        yield Request("Verifying", request_result, (None,))
        return dict(prepared=dict(references=[ref]), snapshot=dict(lines=deepcopy(state["lines"])))

    def mutate(proposal):
        threads.append(get_ident())
        state["writes"] += 1
        if state["fail"]:
            raise RuntimeError("Stale BOM; prepare again")
        state["lines"] = [
            dict(
                component_revision_id=line.component_revision_id,
                item_number="S000001",
                item_name="Bolt",
                revision_label="A",
                lifecycle_state="working",
                quantity=str(line.quantity),
                position=line.position,
            )
            for line in proposal
        ]

    def apply(plan, proposal):
        assert get_ident() == main_thread
        yield Request("Applying", mutate, (proposal,), mutates=True, cancellable=False)

    class Client:
        def bom_revision_updates(self, lines):
            threads.append(get_ident())
            return {key: "B"}

    dialog = BOMDialog(None, "A000001", Client(), load, prepare, apply)
    dialog.show()

    def wait(predicate):
        deadline = time.monotonic() + 5
        while not predicate() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.002)
        assert predicate(), dialog.status.text()

    wait(
        lambda: (
            dialog.job is None
            and "loaded" in dialog.status.text()
            or "no published" in dialog.status.text()
        )
    )
    yield dialog, state, wait, app
    wait(lambda: dialog.job is None)
    dialog.reject()
    app.processEvents()
    assert threads and all(thread != main_thread for thread in threads)


def test_default_inclusion_apply_refresh_and_noop(case):
    dialog, state, wait, app = case
    assert "0.081 kg" in dialog.mass.text()
    dialog.update_button.click()
    wait(lambda: dialog.job is None and dialog.plan is not None)
    assert dialog.checks[0][0].isChecked()
    assert dialog.scroll.isHidden()
    assert dialog.apply_button.isEnabled()
    dialog.apply_button.click()
    wait(lambda: dialog.job is None and state["writes"] == 1)
    assert dialog.review.isHidden()
    assert dialog.tree.topLevelItemCount() == 1
    wait(lambda: dialog.notice_job is None)
    assert dialog.tree.topLevelItem(0).text(5) == "Newer: B"
    dialog.update_button.click()
    wait(lambda: dialog.job is None and dialog.plan is not None)
    assert "up to date" in dialog.status.text()
    assert not dialog.apply_button.isEnabled()
    assert state["writes"] == 1


def test_empty_replacement_confirmation_cancel_then_apply(case, monkeypatch):
    dialog, state, wait, app = case
    dialog.update_button.click()
    wait(lambda: dialog.job is None and dialog.plan is not None)
    dialog.apply_button.click()
    wait(lambda: dialog.job is None and state["writes"] == 1)
    dialog.update_button.click()
    wait(lambda: dialog.job is None and dialog.plan is not None)
    assert dialog.review.isEnabled()
    dialog.choose.click()
    dialog.checks[0][0].setChecked(False)
    assert "EMPTY" in dialog.changes.toPlainText()
    monkeypatch.setattr(QtWidgets.QMessageBox, "question", lambda *args: QtWidgets.QMessageBox.No)
    dialog.apply_button.click()
    assert state["writes"] == 1
    monkeypatch.setattr(QtWidgets.QMessageBox, "question", lambda *args: QtWidgets.QMessageBox.Yes)
    dialog.apply_button.click()
    wait(lambda: dialog.job is None and state["writes"] == 2)
    assert not state["lines"]


def test_stale_write_invalidates_proposal_and_does_not_retry(case):
    dialog, state, wait, app = case
    dialog.update_button.click()
    wait(lambda: dialog.job is None and dialog.plan is not None)
    state["fail"] = True
    dialog.apply_button.click()
    # Closing during a write must preserve the window and its operation.
    dialog.reject()
    assert dialog.isVisible()
    wait(lambda: dialog.job is None)
    assert dialog.plan is None and dialog.review.isHidden()
    assert "Stale BOM" in dialog.status.text()
    assert "outcome may be unknown" in dialog.status.text()
    assert state["writes"] == 1
