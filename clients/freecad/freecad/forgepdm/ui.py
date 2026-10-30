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
