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
            "Select component occurrences to count. Local geometry is excluded.\n"
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
    dialog.setWindowTitle("Replace with New Revision — Occurrences")
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


def review_component_replacement(source_label, target_revision, occurrences, snapshot):
    message = (
        "Replace {} with revision {} ({})?\n\n{}\n\n"
        "Snapshot: {}\n\n"
        "Placements and link objects will be retained. Inspect geometry and joints afterward.\n"
        "Save/upload and synchronize the BOM separately to persist the change."
    ).format(
        source_label,
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
