"""Column layouts, page placement and custom row text in one drawing BOM editor."""

import copy
import json
from uuid import uuid4

from . import drawing_bom as model, settings
from .ui import QtCore, QtWidgets


class DrawingBOMDialog(QtWidgets.QDialog):
    def __init__(self, parent, report, pages, preferred=None):
        super().__init__(parent)
        self.report, self.pages = report, pages
        self.notes = {}
        self.keys = []
        self.preview_bindings = []
        self.setWindowTitle("Insert / Update Drawing BOM")
        self.resize(1000, 760)
        box = QtWidgets.QVBoxLayout(self)
        label = QtWidgets.QLabel(
            "Stored direct engineering BOM. Unsaved CAD changes are not included. Update preserves matching custom row text; no server BOM writes."
        )
        label.setWordWrap(True)
        box.addWidget(label)
        form = QtWidgets.QFormLayout()
        self.page = QtWidgets.QComboBox()
        for page in pages:
            self.page.addItem(page.Label, page)
        self.target = QtWidgets.QComboBox()
        form.addRow("Page", self.page)
        form.addRow("Table", self.target)
        self.presets = QtWidgets.QComboBox()
        self.presets.addItem("Default", copy.deepcopy(model.DEFAULT))
        self.preset_error = ""
        try:
            saved = json.loads(
                (settings._parameters().GetString("DrawingBOMLayouts", "{}") or "{}")
            )
            if not isinstance(saved, dict) or len(saved) > 30:
                raise ValueError("Invalid saved layouts")
            for name, value in saved.items():
                self.presets.addItem(name, model.layout(value))
        except (ValueError, TypeError, KeyError) as error:
            self.preset_error = "Saved layouts need inspection: " + str(error)
        preset_row = QtWidgets.QHBoxLayout()
        preset_row.addWidget(self.presets, 1)
        load = QtWidgets.QPushButton("Load layout")
        save = QtWidgets.QPushButton("Save layout as…")
        preset_row.addWidget(load)
        preset_row.addWidget(save)
        form.addRow("Layout", preset_row)
        box.addLayout(form)
        self.columns = QtWidgets.QTableWidget(0, 5)
        self.columns.setHorizontalHeaderLabels(
            ["Field", "Heading", "Width (mm)", "Alignment", "Mass unit"]
        )
        box.addWidget(self.columns)
        actions = QtWidgets.QHBoxLayout()
        for title, callback in [
            ("Add column", self.add_column),
            ("Remove", self.remove_column),
            ("Move up", lambda: self.move(-1)),
            ("Move down", lambda: self.move(1)),
        ]:
            button = QtWidgets.QPushButton(title)
            button.clicked.connect(callback)
            actions.addWidget(button)
        box.addLayout(actions)
        sizing = QtWidgets.QHBoxLayout()
        self.font = QtWidgets.QDoubleSpinBox()
        self.font.setRange(1.5, 10)
        self.font.setValue(3)
        self.font.setSuffix(" mm text")
        self.precision = QtWidgets.QSpinBox()
        self.precision.setRange(0, 6)
        self.precision.setValue(3)
        self.precision.setSuffix(" mass decimals")
        self.x = QtWidgets.QDoubleSpinBox()
        self.x.setRange(0, 2000)
        self.x.setSuffix(" mm X")
        self.y = QtWidgets.QDoubleSpinBox()
        self.y.setRange(0, 2000)
        self.y.setSuffix(" mm Y")
        for widget in [self.font, self.precision, self.x, self.y]:
            sizing.addWidget(widget)
        refresh = QtWidgets.QPushButton("Preview / edit custom text")
        refresh.clicked.connect(self.preview)
        sizing.addWidget(refresh)
        box.addLayout(sizing)
        self.grid = QtWidgets.QTableWidget()
        box.addWidget(self.grid, 1)
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
        self.target.currentIndexChanged.connect(self.target_changed)
        load.clicked.connect(lambda: self.load_layout(self.presets.currentData()))
        save.clicked.connect(self.save_layout)
        if preferred:
            for i, page in enumerate(pages):
                if preferred in page.Views:
                    self.page.setCurrentIndex(i)
        self.page_changed()
        if preferred:
            for i in range(self.target.count()):
                if self.target.itemData(i) is preferred:
                    self.target.setCurrentIndex(i)

    def page_changed(self, *_):
        self.target.blockSignals(True)
        self.target.clear()
        self.target.addItem("New table", None)
        for obj in self.page.currentData().Views:
            if hasattr(obj, "PDMTableData"):
                self.target.addItem(obj.Label, obj)
        self.target.blockSignals(False)
        self.target_changed()

    def target_changed(self, *_):
        obj = self.target.currentData()
        self.target_valid = False
        self.preview_bindings = []
        try:
            data = model.read_table(obj) if obj else None
            self.notes = copy.deepcopy(data["notes"]) if data else {}
            self.load_layout(data["layout"] if data else self.presets.currentData())
            self.x.setValue(
                float(obj.X) if obj else float(self.page.currentData().Template.Width) / 2
            )
            self.y.setValue(float(obj.Y) if obj else 40)
            self.target_valid = True
        except (ValueError, TypeError, KeyError) as error:
            self.status.setText(str(error))

    def stash(self):
        for row, column, key, field in self.preview_bindings:
            item = self.grid.item(row, column)
            if item:
                self.notes.setdefault(key, {})[field] = item.text()

    def load_layout(self, value):
        self.stash()
        value = model.layout(value)
        self.font.setValue(value["font"])
        self.precision.setValue(value["precision"])
        self.columns.setRowCount(0)
        self.keys = []
        for column in value["columns"]:
            self.append(column)
        self.preview()

    def append(self, column):
        index = self.columns.rowCount()
        self.columns.insertRow(index)
        self.keys.append(column.get("key", str(uuid4())))
        for cell, values, current in [
            (0, list(model.FIELDS), column["field"]),
            (3, ["left", "center", "right"], column["align"]),
            (4, ["kg", "g"], column.get("unit", "kg")),
        ]:
            combo = QtWidgets.QComboBox()
            combo.addItems(values)
            combo.setCurrentText(current)
            self.columns.setCellWidget(index, cell, combo)
        self.columns.setItem(index, 1, QtWidgets.QTableWidgetItem(column["heading"]))
        self.columns.setItem(index, 2, QtWidgets.QTableWidgetItem(str(column["width"])))

    def definition(self):
        return model.layout(
            {
                "font": self.font.value(),
                "precision": self.precision.value(),
                "columns": [
                    {
                        "field": self.columns.cellWidget(i, 0).currentText(),
                        "heading": self.columns.item(i, 1).text(),
                        "width": float(self.columns.item(i, 2).text()),
                        "align": self.columns.cellWidget(i, 3).currentText(),
                        "unit": self.columns.cellWidget(i, 4).currentText(),
                        "key": self.keys[i],
                    }
                    for i in range(self.columns.rowCount())
                ],
            }
        )

    def add_column(self):
        self.stash()
        self.append({"field": "custom", "heading": "Notes", "width": 30, "align": "left"})
        self.preview()

    def remove_column(self):
        self.stash()
        index = self.columns.currentRow()
        if index >= 0:
            self.columns.removeRow(index)
            self.keys.pop(index)
        self.preview()

    def move(self, direction):
        try:
            self.stash()
            definition = self.definition()
            index = self.columns.currentRow()
            other = index + direction
            if index < 0 or not 0 <= other < len(self.keys):
                return
            definition["columns"][index], definition["columns"][other] = (
                definition["columns"][other],
                definition["columns"][index],
            )
            self.load_layout(definition)
            self.columns.setCurrentCell(other, 1)
        except (ValueError, AttributeError) as error:
            self.status.setText(str(error))

    def preview(self):
        try:
            self.stash()
            definition = self.definition()
            _, width, height = model.render(
                self.report, definition, self.notes, model.measure_text(definition["font"])
            )
            self.preview_bindings = []
            self.grid.setColumnCount(len(definition["columns"]))
            self.grid.setRowCount(len(self.report["lines"]))
            self.grid.setHorizontalHeaderLabels(
                [column["heading"] for column in definition["columns"]]
            )
            for row, line in enumerate(self.report["lines"]):
                for i, column in enumerate(definition["columns"]):
                    item = QtWidgets.QTableWidgetItem(
                        model.cell(line, column, self.notes, definition["precision"])
                    )
                    if column["field"] != "custom":
                        item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
                    else:
                        self.preview_bindings.append((row, i, model.row_key(line), column["key"]))
                    self.grid.setItem(row, i, item)
            self.status.setText(
                f"Table size: {width:.1f} × {height:.1f} mm. X/Y are the table centre. "
                + self.preset_error
            )
            return True
        except (ValueError, KeyError, AttributeError) as error:
            self.status.setText(str(error))
            return False

    def save_layout(self):
        try:
            value = self.definition()
            name, ok = QtWidgets.QInputDialog.getText(self, "Save BOM layout", "Layout name")
            if not ok or not name.strip():
                return
            if len(name) > 80:
                raise ValueError("Layout name is too long")
            saved = json.loads(
                (settings._parameters().GetString("DrawingBOMLayouts", "{}") or "{}")
            )
            if name not in saved and len(saved) >= 30:
                raise ValueError("At most 30 layouts are supported")
            saved[name] = value
            settings._parameters().SetString("DrawingBOMLayouts", json.dumps(saved))
            index = self.presets.findText(name)
            if index >= 0:
                self.presets.setItemData(index, value)
            else:
                self.presets.addItem(name, value)
        except (ValueError, TypeError) as error:
            self.status.setText(str(error))

    def accept(self):
        if not self.target_valid:
            self.status.setText("The saved table cannot be read safely; select another target")
            return
        if self.preview():
            try:
                model.placement(
                    self.page.currentData(),
                    self.target.currentData(),
                    self.report,
                    self.definition(),
                    self.notes,
                    self.x.value(),
                    self.y.value(),
                )
            except (ValueError, AttributeError) as error:
                self.status.setText(str(error))
                return
            super().accept()
