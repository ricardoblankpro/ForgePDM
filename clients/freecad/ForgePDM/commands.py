"""FreeCAD Workbench commands backed by the ForgePDM HTTP API."""

import os
import re

import FreeCAD
import FreeCADGui

from ForgePDM.api import ForgePDMClient, ForgePDMError
from ForgePDM.session import Session
from ForgePDM.ui import QtWidgets, ask_choice, ask_text, error, information, warning


METADATA_OBJECT = "ForgePDM_Metadata"


def _main_window():
    try:
        return FreeCADGui.getMainWindow()
    except Exception:
        return None


def _metadata(document, create=False):
    obj = document.getObject(METADATA_OBJECT)
    if obj is None and create:
        obj = document.addObject("App::FeaturePython", METADATA_OBJECT)
        obj.Label = "ForgePDM Metadata"
        try:
            obj.ViewObject.Visibility = False
        except Exception:
            pass
    if obj is not None:
        for name in ("ItemId", "RevisionId", "ItemNumber", "RevisionLabel"):
            if not hasattr(obj, name):
                obj.addProperty("App::PropertyString", name, "ForgePDM")
    return obj


def _set_metadata(document, **values):
    obj = _metadata(document, create=True)
    for key, value in values.items():
        setattr(obj, key, str(value or ""))
    return obj


def _require_document():
    document = FreeCAD.ActiveDocument
    if document is None:
        raise RuntimeError("Open a FreeCAD document first")
    return document


def _save_document(document):
    path = getattr(document, "FileName", "")
    if not path:
        path, _filter = QtWidgets.QFileDialog.getSaveFileName(
            _main_window(), "Save FreeCAD document", document.Label + ".FCStd", "FreeCAD document (*.FCStd)"
        )
        if not path:
            raise RuntimeError("Save the document before uploading")
        if not path.lower().endswith(".fcstd"):
            path += ".FCStd"
        document.saveAs(path)
    else:
        document.recompute()
        document.save()
    return os.path.abspath(document.FileName)


def _require_metadata(document):
    obj = _metadata(document)
    if obj is None or not obj.ItemId or not obj.RevisionId:
        raise RuntimeError("This document is not linked to a ForgePDM item yet")
    return obj


def _run(action):
    try:
        action()
    except ForgePDMError as exception:
        error("ForgePDM", str(exception))
    except Exception as exception:
        error("ForgePDM", str(exception))


class LoginCommand:
    def GetResources(self):
        return {"MenuText": "Log In", "ToolTip": "Connect this FreeCAD session to ForgePDM"}

    def IsActive(self):
        return True

    def Activated(self):
        def action():
            base_url = ask_text("ForgePDM Login", "Server URL", "http://127.0.0.1:8000")
            if not base_url:
                return
            username = ask_text("ForgePDM Login", "Username")
            if not username:
                return
            password = ask_text("ForgePDM Login", "Password", password=True)
            if password is None:
                return
            client = ForgePDMClient(base_url)
            user = client.login(username, password)
            Session.set_client(client, user)
            information("ForgePDM", "Logged in as {}".format(user.get("display_name", username)))

        _run(action)


class LogoutCommand:
    def GetResources(self):
        return {"MenuText": "Log Out", "ToolTip": "End the ForgePDM session"}

    def IsActive(self):
        return Session.client is not None

    def Activated(self):
        try:
            Session.clear()
            information("ForgePDM", "Logged out")
        except ForgePDMError as exception:
            warning("ForgePDM", str(exception))


class UploadCommand:
    def GetResources(self):
        return {"MenuText": "Create / Upload Current Document", "ToolTip": "Create a ForgePDM item if needed, then upload this document"}

    def IsActive(self):
        return Session.client is not None

    def Activated(self):
        def action():
            client = Session.require_client()
            document = _require_document()
            local_path = _save_document(document)
            metadata = _metadata(document)
            if metadata is None or not metadata.ItemId:
                kind = ask_choice("New ForgePDM Item", "Item kind", ["part", "assembly"], "part")
                if not kind:
                    return
                project_id = ask_text(
                    "New ForgePDM Item", "Project UUID (leave blank for administrator-only item)", ""
                )
                result = client.create_item(kind, document.Label, project_id or None)
                _set_metadata(
                    document,
                    ItemId=result["id"],
                    RevisionId=result["current_revision_id"],
                    ItemNumber=result["number"],
                    RevisionLabel="A",
                )
                document.recompute()
                document.save()
                metadata = _require_metadata(document)
            response = client.upload_file(
                metadata.RevisionId,
                local_path,
                dataset_type="native_cad",
                name="Native CAD",
            )
            information(
                "ForgePDM",
                "Uploaded {} as {} (revision {})".format(
                    os.path.basename(local_path), metadata.ItemNumber, metadata.RevisionLabel
                ),
            )

        _run(action)


class CheckoutCommand:
    def GetResources(self):
        return {"MenuText": "Acquire / Renew Checkout", "ToolTip": "Acquire or extend the active revision checkout"}

    def IsActive(self):
        return Session.client is not None and FreeCAD.ActiveDocument is not None

    def Activated(self):
        def action():
            document = _require_document()
            metadata = _require_metadata(document)
            checkout = Session.require_client().acquire_checkout(metadata.RevisionId)
            information("ForgePDM", "Checkout held until {}".format(checkout["expires_at"]))

        _run(action)


class CheckInCommand:
    def GetResources(self):
        return {"MenuText": "Check In Current Revision", "ToolTip": "Record a change note and release your checkout"}

    def IsActive(self):
        return Session.client is not None and FreeCAD.ActiveDocument is not None

    def Activated(self):
        def action():
            document = _require_document()
            metadata = _require_metadata(document)
            note = ask_text("ForgePDM Check In", "Change note")
            if not note:
                return
            _save_document(document)
            Session.require_client().upload_file(
                metadata.RevisionId, document.FileName, "native_cad", "Native CAD"
            )
            Session.require_client().checkin(metadata.RevisionId, note)
            information("ForgePDM", "Revision checked in")

        _run(action)


class ReleaseCommand:
    def GetResources(self):
        return {"MenuText": "Release Current Revision", "ToolTip": "Release a checked-in revision"}

    def IsActive(self):
        return Session.client is not None and FreeCAD.ActiveDocument is not None

    def Activated(self):
        def action():
            metadata = _require_metadata(_require_document())
            Session.require_client().transition(metadata.RevisionId, "released")
            information("ForgePDM", "Revision released")

        _run(action)


class NewRevisionCommand:
    def GetResources(self):
        return {"MenuText": "Create Next Revision", "ToolTip": "Start the next Working revision from a Released item"}

    def IsActive(self):
        return Session.client is not None and FreeCAD.ActiveDocument is not None

    def Activated(self):
        def action():
            document = _require_document()
            metadata = _require_metadata(document)
            note = ask_text("ForgePDM New Revision", "Describe the change")
            if not note:
                return
            result = Session.require_client().create_next_revision(metadata.ItemId, note)
            _set_metadata(
                document,
                RevisionId=result["id"],
                RevisionLabel=result["label"],
            )
            document.recompute()
            document.save()
            Session.require_client().upload_file(
                result["id"], document.FileName, "native_cad", "Native CAD"
            )
            information("ForgePDM", "Created and uploaded revision {}".format(result["label"]))

        _run(action)


class ShowBOMCommand:
    def GetResources(self):
        return {"MenuText": "Show ForgePDM BOM", "ToolTip": "Display the current revision's nested bill of materials"}

    def IsActive(self):
        return Session.client is not None and FreeCAD.ActiveDocument is not None

    def Activated(self):
        def action():
            metadata = _require_metadata(_require_document())
            item = Session.require_client().get_item(metadata.ItemId)
            lines = Session.require_client().get_bom(metadata.RevisionId, recursive=True)
            text = _format_bom(lines)
            dialog = QtWidgets.QDialog(_main_window())
            dialog.setWindowTitle("ForgePDM BOM — {}".format(item["number"]))
            dialog.resize(640, 480)
            layout = QtWidgets.QVBoxLayout(dialog)
            output = QtWidgets.QPlainTextEdit(dialog)
            output.setReadOnly(True)
            output.setPlainText(text or "This revision has no BOM lines.")
            layout.addWidget(output)
            buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok, parent=dialog)
            buttons.accepted.connect(dialog.accept)
            layout.addWidget(buttons)
            dialog.exec_() if hasattr(dialog, "exec_") else dialog.exec()

        _run(action)


class DownloadCommand:
    def GetResources(self):
        return {"MenuText": "Download Item / Assembly", "ToolTip": "Download the current native file and BOM component revisions"}

    def IsActive(self):
        return Session.client is not None

    def Activated(self):
        def action():
            client = Session.require_client()
            item_id = ask_text("Download from ForgePDM", "Item UUID")
            if not item_id:
                return
            destination = QtWidgets.QFileDialog.getExistingDirectory(
                _main_window(), "Choose download folder", os.path.expanduser("~")
            )
            if not destination:
                return
            item = client.get_item(item_id)
            revision = item["current_revision"]
            downloaded = _download_revision(
                client,
                revision["id"],
                item["number"],
                revision["label"],
                destination,
            )
            if downloaded is None:
                raise RuntimeError("No native_cad dataset is attached to the current revision")
            skipped = []
            try:
                lines = client.get_bom(revision["id"], recursive=True)
            except ForgePDMError as exception:
                lines = []
                skipped.append(str(exception))
            for component in _walk_bom(lines):
                try:
                    path = _download_revision(
                        client,
                        component["component_revision_id"],
                        component["item_number"],
                        component["revision_label"],
                        destination,
                    )
                    if path is None:
                        skipped.append("{} Rev{} has no native CAD dataset".format(
                            component["item_number"], component["revision_label"]
                        ))
                except ForgePDMError as exception:
                    skipped.append("{} Rev{}: {}".format(
                        component["item_number"], component["revision_label"], exception
                    ))
            document = FreeCAD.openDocument(downloaded)
            _set_metadata(
                document,
                ItemId=item["id"],
                RevisionId=revision["id"],
                ItemNumber=item["number"],
                RevisionLabel=revision["label"],
            )
            document.save()
            message = "Downloaded and opened {} Rev{}".format(item["number"], revision["label"])
            if skipped:
                message += "\n\nSome BOM files were not downloaded:\n" + "\n".join(skipped)
                warning("ForgePDM", message)
            else:
                information("ForgePDM", message)

        _run(action)


def _download_revision(client, revision_id, item_number, revision_label, destination):
    datasets = client.list_datasets(revision_id)
    native = [dataset for dataset in datasets if dataset["dataset_type"] == "native_cad"]
    if not native:
        return None
    dataset = sorted(native, key=lambda record: record["created_at"])[-1]
    if not dataset["files"]:
        return None
    file_record = dataset["files"][0]
    extension = os.path.splitext(file_record["original_filename"])[1] or ".FCStd"
    stem = re.sub(r"[^A-Za-z0-9_.-]", "_", "{}_Rev{}".format(item_number, revision_label))
    filename = stem + extension
    path = os.path.join(destination, filename)
    suffix = 1
    while os.path.exists(path):
        filename = "{}_{}{}".format(stem, suffix, extension)
        path = os.path.join(destination, filename)
        suffix += 1
    return client.download_file(file_record["id"], path)


def _walk_bom(lines):
    for line in lines:
        yield line
        for child in _walk_bom(line.get("children", [])):
            yield child


def _format_bom(lines, depth=0):
    formatted = []
    for line in lines:
        indent = "  " * depth
        formatted.append(
            "{}{}. {} {} Rev{}  x{}  {}".format(
                indent,
                line["position"],
                line["item_number"],
                line["item_name"],
                line["revision_label"],
                line["quantity"],
                line["lifecycle_state"],
            )
        )
        formatted.extend(_format_bom(line.get("children", []), depth + 1))
    return "\n".join(formatted)
