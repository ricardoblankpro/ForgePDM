"""Qt compatibility helpers for FreeCAD's PySide versions."""

try:
    from PySide import QtCore, QtGui, QtWidgets
except ImportError:
    try:
        from PySide6 import QtCore, QtGui, QtWidgets
    except ImportError:
        from PySide2 import QtCore, QtGui, QtWidgets


def parent_window():
    try:
        import FreeCADGui

        return FreeCADGui.getMainWindow()
    except Exception:
        return None


def select_drawing_pages(pages):
    dialog = QtWidgets.QDialog(parent_window())
    dialog.setWindowTitle("Publish Drawing PDFs — select pages")
    layout = QtWidgets.QVBoxLayout(dialog)
    choices = QtWidgets.QListWidget(dialog)
    for page in pages:
        item = QtWidgets.QListWidgetItem("{} ({})".format(page["page_label"], page["page_name"]))
        item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
        item.setCheckState(QtCore.Qt.Checked)
        choices.addItem(item)
    layout.addWidget(choices)
    buttons = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    dialog.resize(480, 360)
    if not execute_dialog(dialog):
        return None
    return [
        page
        for index, page in enumerate(pages)
        if choices.item(index).checkState() == QtCore.Qt.Checked
    ]


def review_drawing_publication(plan, pages):
    box = QtWidgets.QMessageBox(parent_window())
    box.setWindowTitle("Review Drawing PDF Publication")
    box.setTextFormat(QtCore.Qt.PlainText)
    box.setText(
        "Publish {} drawing page(s) for {} revision {}?\n\nSource CAD uploaded: {}\n\n{}\n\nPDFs are generated from this exact uploaded snapshot. Your original document and checkout are preserved.".format(
            len(pages),
            plan["revision"]["item_number"],
            plan["revision"]["label"],
            plan["source_created_at"],
            "\n".join(page["page_label"] for page in pages),
        )
    )
    box.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
    box.setDefaultButton(QtWidgets.QMessageBox.No)
    return execute_dialog(box) == QtWidgets.QMessageBox.Yes


def information(title, message):
    QtWidgets.QMessageBox.information(parent_window(), title, message)


def warning(title, message):
    QtWidgets.QMessageBox.warning(parent_window(), title, message)


def error(title, message):
    QtWidgets.QMessageBox.critical(parent_window(), title, message)


def ask_text(title, label, default="", password=False):
    dialog = QtWidgets.QInputDialog(parent_window())
    dialog.setWindowTitle(title)
    dialog.setLabelText(label)
    dialog.setTextValue(default)
    if password:
        dialog.setTextEchoMode(QtWidgets.QLineEdit.Password)
    result = dialog.exec_() if hasattr(dialog, "exec_") else dialog.exec()
    if result:
        return dialog.textValue()
    return None


def ask_choice(title, label, choices, default=None):
    initial = default if default in choices else (choices[0] if choices else "")
    value, accepted = QtWidgets.QInputDialog.getItem(
        parent_window(), title, label, choices, choices.index(initial) if initial else 0, False
    )
    return value if accepted else None


def execute_dialog(dialog):
    return dialog.exec() if hasattr(dialog, "exec") else dialog.exec_()


def select_bom_occurrences(references):
    dialog = QtWidgets.QDialog(parent_window())
    dialog.setWindowTitle("Select engineering BOM occurrences")
    layout = QtWidgets.QVBoxLayout(dialog)
    layout.addWidget(
        QtWidgets.QLabel(
            "Select linked components and associated fasteners to count. Other local geometry is excluded.\n"
            "External assemblies count as one component; their children are not flattened."
        )
    )
    checks = []
    scroll = QtWidgets.QScrollArea()
    scroll.setWidgetResizable(True)
    content = QtWidgets.QWidget()
    rows = QtWidgets.QVBoxLayout(content)
    for reference in references:
        check = QtWidgets.QCheckBox(
            "{} → {}".format(
                reference["object_name"],
                reference.get("component_label", reference["target_revision_id"]),
            )
        )
        rows.addWidget(check)
        checks.append((check, reference))
    scroll.setWidget(content)
    layout.addWidget(scroll)
    dialog.resize(720, 480)
    buttons = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, parent=dialog
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if not execute_dialog(dialog):
        return None
    return [
        (ref["object_name"], ref["property_name"]) for check, ref in checks if check.isChecked()
    ]


def review_bom(current, proposed):
    from .bom import quantity_changes

    dialog = QtWidgets.QDialog(parent_window())
    dialog.setWindowTitle("Review BOM replacement")
    dialog.resize(800, 600)
    layout = QtWidgets.QVBoxLayout(dialog)
    text = QtWidgets.QPlainTextEdit()
    text.setReadOnly(True)
    sections = ["QUANTITY CHANGES (exact component revisions)"]
    sections.extend("{}: {} → {}".format(*change) for change in quantity_changes(current, proposed))
    sections.append("\nCURRENT ENGINEERING BOM (including manual lines)")
    sections.extend(
        "Position {position}: {item_number} / {revision_label} — {component_revision_id} × {quantity}".format(
            **line
        )
        for line in current
    )
    sections.append("\nPROPOSED ENGINEERING BOM")
    for line in proposed:
        sections.append(
            "Position {}: {} — {} × {}\n  Occurrences: {}".format(
                line.position,
                line.component_label,
                line.component_revision_id,
                line.quantity,
                ", ".join(key[0] for key in line.occurrences),
            )
        )
    if not proposed:
        sections.append("EMPTY — this will remove every current line.")
    text.setPlainText("\n".join(sections))
    layout.addWidget(text)
    consent = QtWidgets.QCheckBox(
        "Replace the entire BOM, including manual lines, with this proposal"
    )
    layout.addWidget(consent)
    buttons = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, parent=dialog
    )
    buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(False)
    consent.toggled.connect(buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    return bool(execute_dialog(dialog) and consent.isChecked())


def login_form(values):
    dialog = QtWidgets.QDialog(parent_window())
    dialog.setWindowTitle("Connect to ForgePDM")
    layout = QtWidgets.QFormLayout(dialog)
    server = QtWidgets.QLineEdit(values["url"])
    username = QtWidgets.QLineEdit(values["username"])
    password = QtWidgets.QLineEdit()
    password.setEchoMode(QtWidgets.QLineEdit.Password)
    timeout = QtWidgets.QSpinBox()
    timeout.setRange(1, 300)
    timeout.setValue(values["timeout"])
    timeout.setSuffix(" seconds")
    for label, widget in (
        ("Server", server),
        ("Username", username),
        ("Password", password),
        ("Request timeout", timeout),
    ):
        layout.addRow(label, widget)
    buttons = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, parent=dialog
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addRow(buttons)
    if not execute_dialog(dialog):
        password.clear()
        return None
    result = (server.text().strip(), username.text().strip(), password.text(), timeout.value())
    password.clear()
    return result


def select_replacement_occurrences(references, selected_names):
    dialog = QtWidgets.QDialog(parent_window())
    dialog.setWindowTitle("Select Component Occurrences to Replace")
    dialog.resize(650, 420)
    layout = QtWidgets.QVBoxLayout(dialog)
    layout.addWidget(QtWidgets.QLabel("Choose the direct component occurrences to replace."))
    checks = []
    for reference in references:
        check = QtWidgets.QCheckBox(reference["occurrence_label"])
        check.setChecked(not selected_names or reference["object_name"] in selected_names)
        layout.addWidget(check)
        checks.append((check, reference["object_name"]))
    buttons = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, parent=dialog
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if not execute_dialog(dialog):
        return None
    return [name for check, name in checks if check.isChecked()]


def review_component_replacement(
    source_label, target_revision, occurrences, snapshot, target_item=None
):
    message = (
        "Replace {} with {} revision {} ({})?\n\n{}\n\n"
        "Snapshot: {}\n\n"
        "Placements and link objects will be retained. Inspect geometry and joints afterward.\n"
        "Save/upload and synchronize the BOM separately to persist the change."
    ).format(
        source_label,
        target_item or "the same item's",
        target_revision["label"],
        target_revision["lifecycle_state"],
        "\n".join(occurrences),
        snapshot,
    )
    return (
        QtWidgets.QMessageBox.question(
            parent_window(),
            "Review Component Revision Replacement",
            message,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        == QtWidgets.QMessageBox.Yes
    )


def standard_specification_dialog(geometry):
    """Select controlled specification values; catalog text is generated, not typed."""
    from . import standard_options as options

    dialog = QtWidgets.QDialog(parent_window())
    dialog.setWindowTitle("Register Standard Fastener")
    layout = QtWidgets.QVBoxLayout(dialog)
    layout.addWidget(
        QtWidgets.QLabel("Geometry from Fasteners Workbench: " + geometry["Type"].upper())
    )
    form = QtWidgets.QFormLayout()
    kind, family, material, grade, finish = [QtWidgets.QComboBox(dialog) for _ in range(5)]
    for name, combo in [
        ("type", kind),
        ("family", family),
        ("material", material),
        ("grade", grade),
        ("finish", finish),
    ]:
        combo.setObjectName("standard_" + name)
    extended = QtWidgets.QCheckBox("Show extended materials, classes and finishes", dialog)
    extended.setObjectName("standard_extended")
    for label, widget in [
        ("Type", kind),
        ("Family", family),
        ("Material", material),
        ("Mechanical class", grade),
        ("Finish", finish),
    ]:
        widget.setEditable(False)
        widget.setMaxVisibleItems(20)
        form.addRow(label, widget)
    layout.addLayout(form)
    layout.addWidget(extended)
    preview = QtWidgets.QLabel(dialog)
    preview.setObjectName("standard_name_preview")
    preview.setWordWrap(True)
    preview.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
    layout.addWidget(QtWidgets.QLabel("Generated catalog name"))
    layout.addWidget(preview)
    manual = QtWidgets.QCheckBox("Enter mass manually if no supplier match", dialog)
    manual.setObjectName("standard_manual_mass")
    layout.addWidget(manual)
    manual_details = QtWidgets.QWidget(dialog)
    manual_form = QtWidgets.QFormLayout(manual_details)
    manual_value = QtWidgets.QLineEdit()
    manual_value.setObjectName("standard_manual_mass_g")
    manual_value.setMaxLength(100)
    manual_note = QtWidgets.QLineEdit()
    manual_note.setObjectName("standard_manual_mass_note")
    manual_note.setMaxLength(500)
    manual_form.addRow("Mass per piece (g)", manual_value)
    manual_form.addRow("Note (optional)", manual_note)
    layout.addWidget(manual_details)
    manual_details.hide()
    manual.toggled.connect(manual_details.setVisible)
    buttons = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
    )

    def accept():
        if manual.isChecked():
            from decimal import Decimal, InvalidOperation

            try:
                value = Decimal(manual_value.text().strip())
                if not value.is_finite() or not Decimal("1e-9") <= value <= Decimal("1e7"):
                    raise ValueError("invalid mass")
            except (ValueError, InvalidOperation):
                QtWidgets.QMessageBox.warning(
                    dialog, "Mass", "Enter a positive mass per piece in grams."
                )
                return
        dialog.accept()

    buttons.accepted.connect(accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    result = [None]

    def fill(combo, rows, previous=None):
        combo.blockSignals(True)
        combo.clear()
        for entry in rows:
            combo.addItem(entry["label"], entry["id"])
        index = combo.findData(previous)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)

    def update_preview(*args):
        try:
            spec = options.selected_spec(
                geometry,
                material.currentData(),
                grade.currentData(),
                finish.currentData(),
                kind.currentText(),
                family.currentText(),
                extended.isChecked(),
            )
            name, description = options.catalog_text(spec, kind.currentText(), family.currentText())
            result[0] = dict(specification=spec, name=name, description=description)
            preview.setText(name)
            buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(True)
        except ValueError as error:
            result[0] = None
            preview.setText(str(error))
            buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(False)

    def update_dependent(*args):
        fill(
            grade,
            options.grades(
                material.currentData(),
                kind.currentText(),
                family.currentText(),
                geometry,
                extended.isChecked(),
            ),
            grade.currentData(),
        )
        fill(
            finish,
            options.finishes(material.currentData(), extended.isChecked()),
            finish.currentData(),
        )
        update_preview()

    def update_family(*args):
        previous = family.currentText()
        family.blockSignals(True)
        family.clear()
        if classified is None:
            family.addItem("SELECT FAMILY")
        family.addItems(options.TYPES[kind.currentText()])
        index = family.findText(previous)
        family.setCurrentIndex(index if index >= 0 else 0)
        family.blockSignals(False)
        update_dependent()

    def update_materials(*args):
        fill(
            material,
            [o for o in options.MATERIALS if extended.isChecked() or not o["extended"]],
            material.currentData(),
        )
        update_dependent()

    kind.addItems(list(options.TYPES))
    classified = options.classification(geometry)
    if classified:
        kind.setCurrentText(classified[0])
    fill(material, [o for o in options.MATERIALS if not o["extended"]])
    update_family()
    if classified:
        family.setCurrentText(classified[1])
        kind.setEnabled(False)
        family.setEnabled(False)
    else:
        # Unknown standards need an explicit classification choice.
        kind.insertItem(0, "SELECT TYPE")
        kind.setCurrentIndex(0)
        family.clear()
    kind.currentIndexChanged.connect(
        lambda *_: update_family() if kind.currentText() in options.TYPES else update_preview()
    )
    family.currentIndexChanged.connect(update_dependent)
    material.currentIndexChanged.connect(update_dependent)
    grade.currentIndexChanged.connect(update_preview)
    finish.currentIndexChanged.connect(update_preview)
    extended.toggled.connect(update_materials)
    update_dependent()
    dialog.resize(780, 420)
    if not execute_dialog(dialog):
        return None
    selected = result[0]
    if selected is not None and manual.isChecked():
        selected = {
            **selected,
            "manual_mass_g": manual_value.text().strip(),
            "manual_mass_note": manual_note.text().strip(),
        }
    return selected
