"""Persistent BOM viewer with asynchronous requests and one combined CAD review."""

from . import bom
from .assembly_mass import summary
from .jobs import Request, WorkflowJob
from .mass_display import format_mass
from .ui import QtCore, QtWidgets


class BOMDialog(QtWidgets.QDialog):
    def __init__(self, parent, number, client, load, prepare, apply):
        super().__init__(parent)
        self.setWindowTitle("ForgePDM BOM / Mass — " + number)
        self.resize(900, 700)
        self.client, self.load_workflow = client, load
        self.prepare_workflow, self.apply_workflow = prepare, apply
        self.job = self.notice_job = None
        self.plan = None
        self.lines = []
        self.report = None
        self.retired_notices = []
        self.updates = {}
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("Published BOM — exact recorded revisions"))
        self.view = QtWidgets.QComboBox()
        for key, label in [
            ("direct", "Direct"),
            ("indented", "Indented"),
            ("flattened", "Flattened"),
        ]:
            self.view.addItem(label, key)
        self.view.setCurrentIndex(1)
        self.view.currentIndexChanged.connect(self.render_view)
        layout.addWidget(self.view)
        self.mass = QtWidgets.QLabel("Loading published mass…")
        self.mass.setWordWrap(True)
        layout.addWidget(self.mass)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(
            [
                "Position",
                "Item",
                "Description",
                "Revision",
                "Qty / parent",
                "Qty / root",
                "Unit mass (kg)",
                "Mass / root (kg)",
                "Lifecycle",
                "Updates",
            ]
        )
        layout.addWidget(self.tree)
        self.status = QtWidgets.QLabel("Loading published BOM…")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.review = QtWidgets.QGroupBox("CAD proposal — replaces the direct engineering BOM")
        review_layout = QtWidgets.QVBoxLayout(self.review)
        explanation = QtWidgets.QLabel(
            "Supported components are included by default. Previous custom exclusions cannot be inferred; review the changes below."
        )
        explanation.setWordWrap(True)
        review_layout.addWidget(explanation)
        self.choose = QtWidgets.QPushButton("Choose components…")
        self.choose.setCheckable(True)
        review_layout.addWidget(self.choose)
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setMaximumHeight(160)
        self.choose.toggled.connect(self.scroll.setVisible)
        review_layout.addWidget(self.scroll)
        self.scroll.hide()
        self.changes = QtWidgets.QPlainTextEdit()
        self.changes.setReadOnly(True)
        review_layout.addWidget(self.changes)
        self.apply_button = QtWidgets.QPushButton("Apply BOM changes")
        self.apply_button.clicked.connect(self.apply)
        review_layout.addWidget(self.apply_button)
        layout.addWidget(self.review)
        self.review.hide()
        row = QtWidgets.QHBoxLayout()
        self.update_button = QtWidgets.QPushButton("Update from CAD")
        self.update_button.clicked.connect(self.prepare)
        row.addWidget(self.update_button)
        self.refresh_button = QtWidgets.QPushButton("Refresh published BOM")
        self.refresh_button.clicked.connect(self.reload)
        row.addWidget(self.refresh_button)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.reject)
        row.addWidget(close)
        layout.addLayout(row)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(40)
        QtCore.QTimer.singleShot(0, self.reload)

    def start(self, workflow, finished):
        def run():
            result = yield from workflow
            finished(result)

        self.update_button.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.apply_button.setEnabled(False)
        self.view.setEnabled(False)
        self.job = WorkflowJob(run())
        self.job.start()

    def poll(self):
        if self.job:
            self.job.poll()
            if self.job.done:
                job, self.job = self.job, None
                self.update_button.setEnabled(True)
                self.refresh_button.setEnabled(True)
                self.view.setEnabled(True)
                if job.error:
                    self.plan = None
                    self.review.hide()
                    message = str(job.error)
                    if job.may_have_changed_server:
                        message += " The server outcome may be unknown. Refresh the published BOM before preparing another update."
                    self.status.setText(message)
        if self.notice_job:
            self.notice_job.poll()
            if self.notice_job.done:
                if self.notice_job.error:
                    self.tree.setToolTip(
                        "Newer-revision notices could not be loaded; published revision pins are unchanged."
                    )
                self.notice_job = None
        for job in list(self.retired_notices):
            job.poll()
            if job.done:
                self.retired_notices.remove(job)

    def reload(self):
        self.plan = None
        self.review.hide()
        if self.notice_job:
            self.notice_job.cancel()
            self.retired_notices.append(self.notice_job)
            self.notice_job = None
        self.report = None
        self.tree.clear()
        self.mass.setText("Loading published mass…")
        self.start(self.load_workflow(), self.loaded)

    def loaded(self, result):
        self.report = result
        self.lines = result["views"]["indented"]
        self.mass.setText(summary(result["mass"]))
        self.updates = {}
        self.render_view()

        def notices():
            updates = yield Request(
                "Checking newer component revisions…",
                self.client.bom_revision_updates,
                (self.lines,),
            )
            if self.report is result:
                self.updates = updates
                for row, revision_id in self.rows:
                    if revision_id in updates:
                        row.setText(9, "Newer: " + str(updates[revision_id]))

        self.notice_job = WorkflowJob(notices())
        self.notice_job.start()

    def render_view(self, *_):
        if self.report is None:
            return
        view = self.view.currentData()
        lines = self.report["views"][view]
        self.tree.clear()
        self.rows = []
        parents = {}
        for line in lines:

            def mass(field):
                value = line.get(field)
                if value is None:
                    return "—"
                prefix = "~" if line.get("mass_source", {}).get("status") == "cad_estimate" else ""
                return prefix + format_mass(value)

            revision_id = line["component_revision_id"]
            row = QtWidgets.QTreeWidgetItem(
                parents.get(line.get("parent_key"), self.tree),
                [
                    str(line["position"]),
                    line["item_number"],
                    line.get("description") or line["item_name"],
                    line["revision_label"],
                    str(line.get("quantity_per_parent") or "—"),
                    str(line["quantity"]),
                    mass("unit_mass"),
                    mass("total_mass"),
                    line["lifecycle_state"],
                    "Newer: " + str(self.updates[revision_id])
                    if revision_id in self.updates
                    else "",
                ],
            )
            row.setToolTip(2, line.get("description") or line["item_name"])
            row.setToolTip(7, line.get("mass_source", {}).get("reason", ""))
            parents[line["row_key"]] = row
            self.rows.append((row, revision_id))
        self.tree.expandToDepth(0)
        self.status.setText(
            "Published BOM loaded. Qty / root and Mass / root refer to one root assembly. "
            "Indented parent/child masses must not be added together. "
            + ("Flattened positions are report row numbers. " if view == "flattened" else "")
            + (
                "Structure incomplete: some assemblies have no stored BOM lines; see mass issues."
                if not self.report.get("structure_complete", True)
                else ""
            )
            if self.lines
            else "This revision has no published BOM lines. Use Update from CAD to prepare one."
        )
        self.tree.setToolTip("")

    def prepare(self):
        self.plan = None
        self.review.hide()
        self.status.setText("Verifying saved/uploaded CAD and checkout…")
        self.start(self.prepare_workflow(), self.prepared)

    def prepared(self, plan):
        self.plan = plan
        self.review.setEnabled(True)
        content = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(content)
        self.checks = []
        for ref in plan["prepared"]["references"]:
            check = QtWidgets.QCheckBox(
                "{} → {}".format(
                    ref["object_name"], ref.get("component_label", ref["target_revision_id"])
                )
            )
            check.setChecked(True)
            check.toggled.connect(self.recalculate)
            layout.addWidget(check)
            self.checks.append((check, ref))
        self.scroll.setWidget(content)
        self.choose.setChecked(False)
        self.scroll.hide()
        self.review.show()
        self.recalculate()

    def recalculate(self, *args):
        self.proposal = bom.propose_lines(
            {"profile": "freecad-app-link-v1", "references": self.plan["prepared"]["references"]},
            [
                (ref["object_name"], ref["property_name"])
                for check, ref in self.checks
                if check.isChecked()
            ],
        )
        current = self.plan["snapshot"]["lines"]
        unchanged, destructive = bom.replacement_status(current, self.proposal)
        labels = {
            line["component_revision_id"]: "{}-{}".format(
                line["item_number"], line["revision_label"]
            )
            for line in current
        }
        labels.update({line.component_revision_id: line.component_label for line in self.proposal})
        changes = [
            "{}: {} → {}".format(labels[key], old, new)
            for key, old, new in bom.quantity_changes(current, self.proposal)
        ]
        changes.append("\nCurrent direct BOM (including any manual lines):")
        changes.extend(
            "Position {}: {}-{} × {}".format(
                line["position"], line["item_number"], line["revision_label"], line["quantity"]
            )
            for line in current
        )
        changes.append("\nProposed direct BOM:")
        changes.extend(
            "Position {}: {} × {}".format(line.position, line.component_label, line.quantity)
            for line in self.proposal
        )
        if not self.proposal:
            changes.append("EMPTY — applying removes every current line.")
        if destructive:
            changes.append(
                "\nThis replacement removes/reduces components or changes custom lines/positions. Manual lines may be affected; confirmation is required."
            )
        self.changes.setPlainText("\n".join(changes))
        self.status.setText(
            "BOM is up to date."
            if unchanged
            else "Review the proposed replacement. Exact revision pins are preserved."
        )
        self.apply_button.setEnabled(not unchanged)

    def apply(self):
        unchanged, destructive = bom.replacement_status(
            self.plan["snapshot"]["lines"], self.proposal
        )
        if unchanged:
            return
        if destructive:
            answer = QtWidgets.QMessageBox.question(
                self,
                "Confirm BOM replacement",
                "Replace the entire direct BOM? Removed components, manual lines and custom positions may be lost. Review the proposal before continuing.",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No,
            )
            if answer != QtWidgets.QMessageBox.Yes:
                return
        self.review.setEnabled(False)
        self.status.setText("Applying reviewed BOM changes…")

        def update():
            yield from self.apply_workflow(self.plan, self.proposal)
            return (yield from self.load_workflow())

        def finished(result):
            self.plan = None
            self.review.hide()
            self.loaded(result)
            self.status.setText("BOM changes applied. Published BOM and mass refreshed.")

        self.start(update(), finished)

    def closeEvent(self, event):
        if self.job is not None or self.notice_job or self.retired_notices:
            event.ignore()
            self.status.setText("Wait for the current operation to finish before closing.")
        else:
            super().closeEvent(event)

    def reject(self):
        if self.job is not None or self.notice_job or self.retired_notices:
            self.status.setText("Wait for the current operation to finish before closing.")
            return
        if self.notice_job:
            self.notice_job.cancel()
        self.timer.stop()
        super().reject()
