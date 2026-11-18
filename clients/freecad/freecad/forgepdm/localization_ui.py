"""Server-owned localization editor; no CAD property writes or backend imports."""

from .ui import QtCore, QtWidgets


def edit(parent, view):
    choice = view.revision.currentData()
    if not choice or not view.item:
        return
    dialog = QtWidgets.QDialog(parent)
    dialog.setWindowTitle("Item description translations")
    layout = QtWidgets.QVBoxLayout(dialog)
    sources = QtWidgets.QComboBox()
    layout.addWidget(sources)
    original = QtWidgets.QLabel()
    original.setWordWrap(True)
    layout.addWidget(original)
    locale = QtWidgets.QComboBox()
    locale.addItem("English", "en")
    locale.addItem("Português (Brasil)", "pt-BR")
    layout.addWidget(locale)
    text = QtWidgets.QPlainTextEdit()
    layout.addWidget(text)
    status = QtWidgets.QLabel()
    status.setWordWrap(True)
    layout.addWidget(status)
    history = QtWidgets.QPlainTextEdit()
    history.setReadOnly(True)
    history.setVisible(False)
    toggle = QtWidgets.QCheckBox("Show historical item text")
    toggle.toggled.connect(history.setVisible)
    layout.addWidget(toggle)
    layout.addWidget(history)
    records = []
    buttons = []

    def selected(*args):
        if not records:
            return
        source = records[sources.currentIndex()]
        for button in buttons:
            button.setEnabled(source.get("can_edit", False))
        text.setReadOnly(not source.get("can_edit", False))
        original.setText(source["source"]["language"] + ": " + source["source"]["text"])
        entries = [
            t
            for t in source["translations"]
            if t["language"] == locale.currentData() and not t["superseded_at"]
        ]
        text.setPlainText(entries[-1]["text"] if entries else "")
        status.setText(
            entries[-1]["state"] + " · " + entries[-1]["provenance_json"] if entries else "missing"
        )

    def loaded(values):
        if isinstance(values, dict) and "error" in values:
            status.setText(values["error"])
            return
        lines = []
        for row in values:
            if row["field"] == "description":
                continue
            lines.append(
                "Previous item name"
                if row["field"] == "designation"
                else "Previous general description"
            )
            lines.extend(v["language"] + ": " + (v["text"] or "(empty)") for v in row["history"])
            lines.extend(
                t["language"] + " · " + t["state"] + ": " + t["text"] for t in row["translations"]
            )
        history.setPlainText("\n".join(lines))
        records[:] = [s for s in values if s["field"] == "description"]
        sources.blockSignals(True)
        sources.clear()
        for row in records:
            sources.addItem(row["field"])
        sources.blockSignals(False)
        selected()

    def visible():
        try:
            return dialog.isVisible()
        except RuntimeError:
            return False

    def request(*args):
        try:
            return view.client._json_request(*args)
        except Exception as error:
            return {"error": str(error)}

    def fetch():
        view.start(
            "Loading translations…",
            request,
            (
                "GET",
                "/api/v1/items/" + view.item["id"] + "/localized-texts?revision_id=" + choice["id"],
            ),
            {},
            visible,
            loaded,
        )

    def change(operation):
        if not records:
            return
        source = records[sources.currentIndex()]
        entries = [
            t
            for t in source["translations"]
            if t["language"] == locale.currentData()
            and t["state"] == "draft"
            and not t["superseded_at"]
        ]
        if operation == "approve" and (
            not entries or text.toPlainText().strip() != entries[-1]["text"]
        ):
            status.setText("Save changes as a draft before approving.")
            return
        payload = {
            "operation": operation,
            "expected_token": source["token"],
            "language": locale.currentData(),
            "text": text.toPlainText(),
            "translation_id": entries[-1]["id"] if entries else None,
        }

        def done(result):
            if "error" in result:
                status.setText(result["error"])
                return
            index = next((i for i, row in enumerate(records) if row["id"] == result["id"]), None)
            if index is None:
                return
            records[index] = result
            selected()

        view.start(
            "Saving localization…",
            request,
            ("POST", "/api/v1/localized-texts/" + source["id"], payload),
            {},
            visible,
            done,
        )

    sources.currentIndexChanged.connect(selected)
    locale.currentIndexChanged.connect(selected)
    for label, operation in [
        ("Save draft", "draft"),
        ("Generate proposal", "generate"),
        ("Approve draft", "approve"),
        ("Confirm/correct source language", "correct-language"),
    ]:
        button = QtWidgets.QPushButton(label)
        button.setEnabled(False)
        buttons.append(button)
        button.clicked.connect(lambda checked=False, op=operation: change(op))
        layout.addWidget(button)
    close = QtWidgets.QPushButton("Close")
    close.clicked.connect(dialog.close)
    layout.addWidget(close)
    dialog.resize(600, 600)
    dialog.setAttribute(QtCore.Qt.WA_DeleteOnClose)
    dialog.show()
    fetch()
    view._localization_dialog = dialog
