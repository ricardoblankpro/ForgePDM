"""Review the exact frozen entry before adopting or reconciling a native balloon."""

from . import drawing_balloons as model, drawing_bom
from .ui import QtCore, QtWidgets


class LinkBalloonDialog(QtWidgets.QDialog):
    def __init__(self, parent, pages, preferred=None):
        super().__init__(parent)
        self.setWindowTitle("Link BOM Balloon")
        self.resize(850, 500)
        box = QtWidgets.QVBoxLayout(self)
        label = QtWidgets.QLabel(
            "Create and place a native TechDraw balloon first. Choose its frozen Direct BOM entry. "
            "Linking replaces its text/expression with the existing BOM Position; leader and style are retained."
        )
        label.setWordWrap(True)
        box.addWidget(label)
        form = QtWidgets.QFormLayout()
        self.page, self.balloon, self.table = [QtWidgets.QComboBox() for _ in range(3)]
        for page in pages:
            self.page.addItem(page.Label, page)
        for title, widget in [
            ("Page", self.page),
            ("Balloon", self.balloon),
            ("BOM table", self.table),
        ]:
            form.addRow(title, widget)
        box.addLayout(form)
        self.grid = QtWidgets.QTableWidget(0, 4)
        self.grid.setHorizontalHeaderLabels(
            ["BOM Position", "Item number", "Revision", "Description"]
        )
        self.grid.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.grid.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.grid.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.grid.horizontalHeader().setStretchLastSection(True)
        box.addWidget(self.grid)
        self.status = QtWidgets.QLabel()
        self.status.setTextFormat(QtCore.Qt.PlainText)
        self.status.setWordWrap(True)
        box.addWidget(self.status)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        box.addWidget(buttons)
        self.page.currentIndexChanged.connect(self.page_changed)
        self.balloon.currentIndexChanged.connect(self.balloon_changed)
        self.table.currentIndexChanged.connect(self.table_changed)
        if preferred is not None:
            for i, page in enumerate(pages):
                if preferred in page.Views:
                    self.page.setCurrentIndex(i)
        self.page_changed()
        if preferred is not None:
            index = self.balloon.findData(preferred)
            if index >= 0:
                self.balloon.setCurrentIndex(index)

    def page_changed(self, *_):
        page = self.page.currentData()
        for combo in (self.balloon, self.table):
            combo.blockSignals(True)
            combo.clear()
        for obj in page.Views:
            if obj.isDerivedFrom("TechDraw::DrawViewBalloon"):
                self.balloon.addItem(obj.Label, obj)
            if hasattr(obj, "PDMTableData"):
                self.table.addItem(obj.Label, obj)
        for combo in (self.balloon, self.table):
            combo.blockSignals(False)
        self.balloon_changed()

    def balloon_changed(self, *_):
        balloon = self.balloon.currentData()
        table = getattr(balloon, "PDMBOMTable", None)
        if table is not None:
            index = self.table.findData(table)
            if index >= 0:
                self.table.setCurrentIndex(index)
        self.table_changed()

    def table_changed(self, *_):
        self.rows = []
        self.grid.setRowCount(0)
        try:
            table = self.table.currentData()
            if table is None or self.balloon.currentData() is None:
                raise ValueError("This page needs a native balloon and a ForgePDM BOM table")
            data = drawing_bom.read_table(table)
            self.rows = model.entries(data)
            self.grid.setRowCount(len(self.rows))
            for i, line in enumerate(self.rows):
                for j, text in enumerate(
                    [
                        str(line["position"]),
                        line["item_number"],
                        line["revision_label"],
                        line.get("description") or line.get("item_name", ""),
                    ]
                ):
                    item = QtWidgets.QTableWidgetItem(text)
                    item.setToolTip(text)
                    self.grid.setItem(i, j, item)
            balloon = self.balloon.currentData()
            self.status.setText(
                "Current text: "
                + balloon.Text
                + ". "
                + getattr(balloon, "PDMBOMStatus", "Unlinked")
                + ". Select the intended entry, then accept to link it."
            )
        except (ValueError, TypeError, KeyError) as error:
            self.status.setText(str(error))

    def row_key(self):
        index = self.grid.currentRow()
        if not 0 <= index < len(self.rows):
            raise ValueError("Select the intended BOM entry")
        return drawing_bom.row_key(self.rows[index])

    def accept(self):
        try:
            self.row_key()
        except ValueError as error:
            self.status.setText(str(error))
            return
        super().accept()
