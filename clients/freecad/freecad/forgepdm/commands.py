"""FreeCAD Workbench commands backed by the ForgePDM HTTP API."""

import os
from pathlib import Path
from uuid import UUID

import FreeCAD
import FreeCADGui

from .api import ForgePDMClient, ForgePDMError
from .session import Session
from .ui import QtWidgets, ask_choice, ask_text, execute_dialog, information, warning
from .jobs import Request
from .resources import icon_path
from .i18n import translate
from . import cad, workspace


METADATA_OBJECT = "ForgePDM_Metadata"


def _project_id(value):
    value = value.strip()
    if not value:
        return None
    try:
        return str(UUID(value))
    except ValueError as exception:
        raise ValueError(
            "Enter the project's ID (UUID), not its project number. "
            "Ask your administrator for the ID of a project you can access."
        ) from exception


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
        if not hasattr(obj, key):
            obj.addProperty("App::PropertyString", key, "ForgePDM")
        setattr(obj, key, str(value or ""))
    return obj


def _require_document():
    document = FreeCAD.ActiveDocument
    if document is None:
        raise RuntimeError("Open a FreeCAD document first")
    return document


def _save_document(document):
    path = getattr(document, "FileName", "")
    needs_copy = bool(path) and (
        not os.access(path, os.W_OK)
        or not os.access(os.path.dirname(os.path.abspath(path)), os.W_OK)
    )
    save_as = not path or needs_copy
    if save_as:
        filename = os.path.basename(path) if path else document.Label + ".FCStd"
        path, _filter = QtWidgets.QFileDialog.getSaveFileName(
            _main_window(),
            "Save a writable FreeCAD copy" if needs_copy else "Save FreeCAD document",
            os.path.join(os.path.expanduser("~"), filename),
            "FreeCAD document (*.FCStd)",
        )
        if not path:
            raise RuntimeError("Save the document before uploading")
        if not path.lower().endswith(".fcstd"):
            path += ".FCStd"
    path = os.path.abspath(path)
    directory = os.path.dirname(path)
    if not os.access(directory, os.W_OK) or (os.path.exists(path) and not os.access(path, os.W_OK)):
        raise RuntimeError(
            "Cannot save to '{}'. Choose a writable location using File > Save As.".format(path)
        )
    try:
        document.recompute()
        if save_as:
            document.saveAs(path)
        else:
            document.save()
    except (OSError, RuntimeError) as exception:
        raise RuntimeError(
            "Could not save FreeCAD document to '{}': {}. "
            "Choose a writable location using File > Save As and try again.".format(path, exception)
        ) from exception
    saved_path = os.path.abspath(document.FileName)
    if not os.path.isfile(saved_path):
        raise RuntimeError("FreeCAD did not create the saved file: '{}'".format(saved_path))
    return saved_path


def _require_metadata(document):
    obj = _metadata(document)
    if obj is None or not obj.ItemId or not obj.RevisionId:
        raise RuntimeError("This document is not linked to a ForgePDM item yet")
    return obj


def _run(action):
    from .tasks import run

    return run(action())


def _guard_document(name, revision_id=None):
    try:
        document = FreeCAD.getDocument(name)
    except NameError:
        document = None
    if document is None:
        raise RuntimeError("The document was closed. Check server state before retrying.")
    if revision_id and _require_metadata(document).RevisionId != revision_id:
        raise RuntimeError("The document revision changed while the request was running.")
    return document


def _select_record(title, prompt, fetch, label, args=(), kwargs=None, allow_projectless=False):
    offset = 0
    while True:
        page = yield Request(
            "Loading " + title.lower() + "…", fetch, args, dict(kwargs or {}, offset=offset)
        )
        records = page["items"]
        labels = [label(record) for record in records]
        choices = list(labels)
        if allow_projectless:
            choices.append("No project (administrators only)")
        if offset:
            choices.append("← Previous page")
        if page["has_more"]:
            choices.append("Next page →")
        if not choices:
            raise RuntimeError(
                "No " + title.lower() + " are available. Check the search or your project access."
            )
        selected = ask_choice(title, prompt, choices)
        if selected is None:
            return None
        if selected == "Next page →":
            offset += page["limit"]
        elif selected == "← Previous page":
            offset = max(0, offset - page["limit"])
        elif selected == "No project (administrators only)":
            return {}
        else:
            return records[labels.index(selected)]


def _choose_workspace(client, document=None):
    from . import settings

    if document is not None and document.FileName:
        try:
            return str(
                workspace.binding(document.FileName, client.base_url, require_uploaded=False)[
                    "root"
                ]
            )
        except workspace.WorkspaceError:
            if any(
                (directory / workspace.MANIFEST).exists()
                for directory in Path(document.FileName).absolute().parents
            ):
                raise
    selected = QtWidgets.QFileDialog.getExistingDirectory(
        _main_window(),
        "Choose ForgePDM workspace",
        settings.workspace_root() or os.path.expanduser("~"),
    )
    if not selected:
        return None
    settings.save_workspace(selected)
    return selected


def _save_managed_as(document, path):
    if os.path.lexists(path):
        raise workspace.WorkspaceError(
            "The new working-copy path already exists; it was not overwritten"
        )
    document.recompute()
    document.saveAs(path)
    cad.rebase_links(document)
    document.save()
    if not os.path.isfile(path):
        raise workspace.WorkspaceError("FreeCAD did not create the managed working copy")
    return path


def _ensure_working(client, document):
    name = document.Name
    if document.FileName and workspace.working_path(document.FileName, client.base_url) is not None:
        return _save_document(document)
    root = _choose_workspace(client, document)
    if root is None:
        return None
    path = yield Request("Preparing isolated working copy…", client.prepare_working, (root,))
    document = _guard_document(name)
    return _save_managed_as(document, path)


def _editable(client, metadata):
    revision = yield Request("Checking revision…", client.get_revision, (metadata.RevisionId,))
    if revision["item_id"] != metadata.ItemId:
        raise workspace.WorkspaceError("Document item/revision metadata is inconsistent")
    if revision["lifecycle_state"] != "working":
        raise workspace.WorkspaceError(
            "This revision is read-only. Create Next Revision before saving/uploading changes."
        )
    return revision


def _upload_native(client, document, path, references):
    if cad.capture(document) != references:
        raise workspace.WorkspaceError(
            "CAD references changed while preparing the upload. Review/save the document before retrying."
        )
    metadata = _require_metadata(document)
    result = yield Request(
        "Uploading verified native CAD snapshot…",
        client.upload_native,
        (path, metadata.RevisionId, metadata.ItemId, references),
        mutates=True,
    )
    if result.get("local_changes_remain") or document.isTouched():
        warning(
            "ForgePDM",
            "The saved snapshot was uploaded, but local changes remain. They were not included in that upload.",
        )
    return result


class Command:
    menu_text = ""
    tooltip = ""
    needs_document = False

    def GetResources(self):
        return {
            "Pixmap": icon_path(),
            "MenuText": translate("ForgePDM", self.menu_text),
            "ToolTip": translate("ForgePDM", self.tooltip),
        }

    def IsActive(self):
        return (
            not Session.busy
            and Session.client is not None
            and (not self.needs_document or FreeCAD.ActiveDocument is not None)
        )

    def Activated(self):
        return _run(self.action)


class LoginCommand(Command):
    menu_text = "Log In"
    tooltip = "Connect to ForgePDM"

    def IsActive(self):
        return not Session.busy

    def action(self):
        from . import settings
        from .ui import login_form

        values = login_form(settings.load())
        if values is None:
            return
        base_url, username, password, timeout = values
        client = ForgePDMClient(base_url, timeout=timeout)
        try:
            user = yield Request(
                "Logging in…", client.login, (username, password), mutates=True, cancellable=False
            )
        finally:
            password = None
            values = None
        previous = Session.clear()
        Session.set_client(client, user)
        settings.save(client.base_url, username, timeout)
        if previous is not None:
            try:
                yield Request(
                    "Closing previous session…", previous.logout, mutates=True, cancellable=False
                )
            except ForgePDMError:
                warning(
                    "ForgePDM", "Connected, but the previous server session could not be revoked."
                )
        information("ForgePDM", "Connected as {}".format(user.get("display_name", username)))


class LogoutCommand(Command):
    menu_text = "Log Out"
    tooltip = "End the ForgePDM session"

    def action(self):
        client = Session.clear()
        if client is not None:
            try:
                yield Request("Logging out…", client.logout, mutates=True, cancellable=False)
            except ForgePDMError as error:
                if error.status != 401:
                    raise
        information("ForgePDM", "Logged out")


class UploadCommand(Command):
    menu_text = "Create / Upload Current Document"
    tooltip = "Save a managed working copy and upload a verified snapshot"
    needs_document = True

    def action(self):
        client = Session.require_client()
        document = _require_document()
        document_name = document.Name
        metadata = _metadata(document)
        project = None
        new = metadata is None or not metadata.ItemId
        if new:
            kind = ask_choice("New ForgePDM Item", "Item kind", ["part", "assembly"], "part")
            if not kind:
                return
            project = yield from _select_record(
                "Projects",
                "Choose a project",
                client.list_projects,
                lambda record: record["project_number"] + " — " + record["name"],
                kwargs={"editable": True},
                allow_projectless=(Session.user or {}).get("role") == "admin",
            )
            if project is None:
                return
        else:
            yield from _editable(client, metadata)
        document = _guard_document(document_name)
        references = cad.capture(document)
        yield Request(
            "Checking linked component snapshots…", client.validate_references, (references,)
        )
        path = yield from _ensure_working(client, document)
        if path is None:
            return
        document = _guard_document(document_name)
        if new:
            yield Request(
                "Validating native CAD references…", client.validate_native, (path, references)
            )
            result = yield Request(
                "Creating item…",
                client.create_item,
                (kind, document.Label, project.get("id")),
                mutates=True,
                cancellable=False,
            )
            document = _guard_document(document_name)
            _set_metadata(
                document,
                ItemId=result["id"],
                RevisionId=result["current_revision_id"],
                ItemNumber=result["number"],
                RevisionLabel="A",
                ServerUrl=client.base_url,
            )
            _save_document(document)
        yield from _upload_native(client, document, path, references)
        information("ForgePDM", "Uploaded the managed CAD snapshot and its exact references.")


class CheckoutCommand(Command):
    menu_text = "Acquire / Renew Checkout"
    tooltip = "Acquire or extend the active revision checkout"
    needs_document = True

    def action(self):
        client = Session.require_client()
        document = _require_document()
        metadata = _require_metadata(document)
        name, revision_id = document.Name, metadata.RevisionId
        result = yield Request(
            "Acquiring checkout…",
            client.acquire_checkout,
            (revision_id,),
            mutates=True,
            cancellable=False,
        )
        document = _guard_document(name, revision_id)
        path = yield from _ensure_working(client, document)
        if path is None:
            information(
                "ForgePDM",
                "Checkout acquired; working-copy selection was canceled. No CAD file was overwritten.",
            )
            return
        information(
            "ForgePDM",
            "Checkout held until {}. Edit the managed working copy.".format(result["expires_at"]),
        )


class CheckInCommand(Command):
    menu_text = "Check In Current Revision"
    tooltip = "Upload saved content and release your checkout"
    needs_document = True

    def action(self):
        client = Session.require_client()
        document = _require_document()
        metadata = _require_metadata(document)
        revision_id = metadata.RevisionId
        note = ask_text("ForgePDM Check In", "Change note")
        if not note:
            return
        yield from _editable(client, metadata)
        references = cad.capture(document)
        path = yield from _ensure_working(client, document)
        if path is None:
            return
        yield from _upload_native(client, document, path, references)
        yield Request(
            "Checking in revision…",
            client.checkin,
            (revision_id, note),
            mutates=True,
            cancellable=False,
        )
        information("ForgePDM", "Revision checked in")


class ReleaseCommand(Command):
    menu_text = "Release Current Revision"
    tooltip = "Release a checked-in revision"
    needs_document = True

    def action(self):
        revision_id = _require_metadata(_require_document()).RevisionId
        yield Request(
            "Releasing revision…",
            Session.require_client().transition,
            (revision_id, "released"),
            mutates=True,
            cancellable=False,
        )
        information("ForgePDM", "Revision released")


class NewRevisionCommand(Command):
    menu_text = "Create Next Revision"
    tooltip = "Start the next Working revision from a Released item"
    needs_document = True

    def action(self):
        client = Session.require_client()
        document = _require_document()
        name = document.Name
        metadata = _require_metadata(document)
        revision_id = metadata.RevisionId
        note = ask_text("ForgePDM New Revision", "Describe the change")
        if not note:
            return
        references = cad.capture(document)
        yield Request(
            "Checking linked component snapshots…", client.validate_references, (references,)
        )
        root = _choose_workspace(client, document)
        if root is None:
            return
        path = yield Request(
            "Preparing next-revision working copy…", client.prepare_working, (root,)
        )
        result = yield Request(
            "Creating next revision…",
            client.create_next_revision,
            (metadata.ItemId, note),
            mutates=True,
            cancellable=False,
        )
        document = _guard_document(name, revision_id)
        _set_metadata(
            document,
            RevisionId=result["id"],
            RevisionLabel=result["label"],
            ServerUrl=client.base_url,
        )
        _save_managed_as(document, path)
        yield from _upload_native(client, document, path, references)
        information(
            "ForgePDM",
            "Created revision {} in a separate working copy; the previous file was preserved.".format(
                result["label"]
            ),
        )


class ShowBOMCommand(Command):
    menu_text = "Show ForgePDM BOM"
    tooltip = "Display the current revision's nested bill of materials"
    needs_document = True

    def action(self):
        client = Session.require_client()
        metadata = _require_metadata(_require_document())
        number, revision_id = metadata.ItemNumber, metadata.RevisionId
        lines = yield Request("Loading BOM…", client.get_bom, (revision_id,), {"recursive": True})
        dialog = QtWidgets.QDialog(_main_window())
        dialog.setWindowTitle("ForgePDM BOM — " + number)
        dialog.resize(640, 480)
        layout = QtWidgets.QVBoxLayout(dialog)
        output = QtWidgets.QPlainTextEdit(dialog)
        output.setReadOnly(True)
        output.setPlainText(_format_bom(lines) or "This revision has no BOM lines.")
        layout.addWidget(output)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok, parent=dialog)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        execute_dialog(dialog)


class DownloadCommand(Command):
    menu_text = "Download Item / Assembly"
    tooltip = "Search items and retrieve a selected revision"

    def action(self):
        client = Session.require_client()
        query = ask_text(
            "Find ForgePDM Item", "Item number, name or description (blank to browse)", ""
        )
        if query is None:
            return
        item = yield from _select_record(
            "Items",
            "Choose an item",
            client.search_items,
            lambda record: record["number"] + " — " + record["name"],
            args=(query,),
        )
        if item is None:
            return
        revision = yield from _select_record(
            "Revisions",
            "Choose the revision to retrieve",
            client.list_revisions,
            lambda record: record["label"] + " — " + record["lifecycle_state"],
            args=(item["id"],),
        )
        if revision is None:
            return
        datasets = yield Request(
            "Loading native CAD snapshots…", client.list_datasets, (revision["id"],)
        )
        choices = [
            (dataset, file_record)
            for dataset in datasets
            if dataset["dataset_type"] == "native_cad"
            for file_record in dataset["files"]
        ]
        if not choices:
            raise workspace.WorkspaceError(
                "No native CAD snapshot is attached to the selected revision"
            )
        selected = 0
        if len(choices) > 1:
            labels = [
                "{}. {} — {} — {}".format(
                    index + 1,
                    dataset["name"],
                    dataset["created_at"],
                    file_record["content_hash"][:8],
                )
                for index, (dataset, file_record) in enumerate(choices)
            ]
            value = ask_choice(
                "CAD Snapshots", "Choose the exact saved snapshot", labels, labels[-1]
            )
            if value is None:
                return
            selected = labels.index(value)
        dataset, file_record = choices[selected]
        root = _choose_workspace(client)
        if root is None:
            return
        configuration = None
        opened = None
        complete = False
        try:
            configuration = yield Request(
                "Retrieving verified CAD configuration…",
                client.retrieve_configuration,
                (root, revision["id"], dataset["id"], file_record["id"]),
            )
            opened = cad.open_configuration(configuration, _set_metadata)
            yield Request(
                "Recording verified workspace configuration…",
                client.finish_configuration,
                (configuration,),
            )
            complete = True
            information(
                "ForgePDM",
                "Opened the exact CAD configuration with verified external links. BOM extraction/synchronization remains a separate step.",
            )
        finally:
            if not complete:
                if opened is not None:
                    retained = cad.close_owned(opened["owned"])
                    if retained:
                        warning(
                            "ForgePDM",
                            "Modified local documents were left open for review: "
                            + ", ".join(retained),
                        )
                if configuration is not None:
                    workspace.incomplete(configuration)


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
