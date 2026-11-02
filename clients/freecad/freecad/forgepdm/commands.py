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
from . import bom, cad, tree_labels, tree_observer, workspace
from .ui import (
    select_bom_occurrences,
    review_bom,
    select_replacement_occurrences,
    review_component_replacement,
)


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
    # App.Document.save() leaves Gui.Document.Modified set in FreeCAD 1.1.
    # Clear it only after successful synchronous save and file verification.
    if hasattr(FreeCADGui, "getDocument"):
        FreeCADGui.getDocument(document.Name).Modified = False
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
    # Revision metadata and native Save As/relink operations can leave an auto
    # transaction open. This owned-copy save completes that controlled operation.
    if document.HasPendingTransaction:
        document.commitTransaction()
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
    yield from _authorize_tree_labels(client, document)
    tree_labels.refresh(document)
    _save_document(document)
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


def _authorize_tree_labels(client, document):
    metadata = _require_metadata(document)
    name, revision_id = document.Name, metadata.RevisionId
    checkout = yield Request("Checking tree-label checkout…", client.get_checkout, (revision_id,))
    document = _guard_document(name, revision_id)
    if workspace.working_path(document.FileName, client.base_url) is None:
        raise workspace.WorkspaceError(
            "Create a managed working copy before refreshing tree labels"
        )
    tree_observer.allow_edit(document, checkout, client, Session.user)


class Command:
    icon_name = "forgepdm"
    menu_text = ""
    tooltip = ""
    needs_document = False

    def GetResources(self):
        return {
            "Pixmap": icon_path(self.icon_name),
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
    icon_name = "login"
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
    icon_name = "logout"
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
    icon_name = "upload"
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
    icon_name = "checkout"
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
        tree_observer.allow_edit(document, result, client, Session.user)
        if tree_labels.refresh(document)["changed"]:
            _save_document(document)
        information(
            "ForgePDM",
            "Checkout held until {}. Edit the managed working copy.".format(result["expires_at"]),
        )


class CheckInCommand(Command):
    icon_name = "checkin"
    menu_text = "Check In Current Revision"
    tooltip = "Upload saved content and release your checkout"
    needs_document = True

    def action(self):
        client = Session.require_client()
        document = _require_document()
        metadata = _require_metadata(document)
        revision_id = metadata.RevisionId
        yield from _editable(client, metadata)
        references = cad.capture(document)
        path = yield from _ensure_working(client, document)
        if path is None:
            return
        yield from _upload_native(client, document, path, references)
        tree_observer.revoke_revision(revision_id)
        yield Request(
            "Checking in revision…",
            client.checkin,
            (revision_id,),
            mutates=True,
            cancellable=False,
        )
        information("ForgePDM", "Revision checked in")


class ReleaseCommand(Command):
    icon_name = "release"
    menu_text = "Release Current Revision"
    tooltip = "Release a checked-in revision"
    needs_document = True

    def action(self):
        revision_id = _require_metadata(_require_document()).RevisionId
        tree_observer.revoke_revision(revision_id)
        yield Request(
            "Releasing revision…",
            Session.require_client().transition,
            (revision_id, "released"),
            mutates=True,
            cancellable=False,
        )
        information("ForgePDM", "Revision released")


class NewRevisionCommand(Command):
    icon_name = "new-revision"
    menu_text = "Create Next Revision"
    tooltip = "Start the next Working revision from a Released item"
    needs_document = True

    def action(self):
        client = Session.require_client()
        document = _require_document()
        name = document.Name
        metadata = _require_metadata(document)
        revision_id = metadata.RevisionId
        if cad.document_modified(document):
            raise workspace.WorkspaceError(
                "Save the source revision before creating a new revision"
            )
        source_path = document.FileName
        note = ask_text("ForgePDM New Revision", "Describe the change")
        if not note:
            return
        item = yield Request("Checking revision source…", client.get_item, (metadata.ItemId,))
        if (
            item["current_revision_id"] != revision_id
            or item["current_revision"]["lifecycle_state"] != "released"
        ):
            raise workspace.WorkspaceError(
                "Create the next revision from the latest Released revision"
            )
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
        document = _guard_document(name, revision_id)
        if cad.document_modified(document) or document.FileName != source_path:
            raise workspace.WorkspaceError("Source revision changed while preparing its copy")
        yield Request(
            "Copying the saved revision without changing assembly references…",
            client.copy_revision_source,
            (source_path, path, references),
        )
        result = yield Request(
            "Creating next revision…",
            client.create_next_revision,
            (metadata.ItemId, note),
            mutates=True,
            cancellable=False,
        )
        source = _guard_document(name, revision_id)
        if cad.document_modified(source) or source.FileName != source_path:
            raise workspace.WorkspaceError(
                "Source revision changed; the new revision copy was preserved"
            )
        # Existing assembly links retain the source document and its old identity.
        document = FreeCAD.openDocument(path)
        FreeCAD.setActiveDocument(document.Name)
        _set_metadata(
            document,
            RevisionId=result["id"],
            RevisionLabel=result["label"],
            ServerUrl=client.base_url,
        )
        _save_document(document)
        if document.HasPendingTransaction:
            document.commitTransaction()
        yield from _upload_native(client, document, path, references)
        information(
            "ForgePDM",
            "Created revision {} in a separate document. Existing assemblies retain revision {}. "
            "Show BOM reports newer component revisions without replacing them.".format(
                result["label"], metadata.RevisionLabel
            ),
        )


class RefreshTreeLabelsCommand(Command):
    icon_name = "tree-labels"
    menu_text = "Refresh ForgePDM Tree Labels"
    tooltip = "Show item, revision and stable occurrence numbers on managed assembly links"
    needs_document = True

    def action(self):
        client = Session.require_client()
        document = _require_document()
        name = document.Name
        metadata = _require_metadata(document)
        revision_id = metadata.RevisionId
        yield from _editable(client, metadata)
        document = _guard_document(name, revision_id)
        yield from _authorize_tree_labels(client, document)
        result = tree_labels.refresh(document)
        message = (
            "Tree labels refreshed. Save/upload the working document to persist changes."
            if result["changed"]
            else "Tree labels are up to date."
        )
        if result["skipped"]:
            message += "\nUnmanaged or unsupported links kept their labels: " + ", ".join(
                result["skipped"]
            )
        information("ForgePDM", message)


class ReplaceRevisionCommand(Command):
    replace_any_item = False
    icon_name = "replace-revision"
    menu_text = "Replace with New Revision…"
    tooltip = "Review and replace direct component occurrences with an exact newer revision"
    needs_document = True

    def action(self):
        from . import replacement

        client = Session.require_client()
        document = _require_document()
        metadata = _require_metadata(document)
        name, revision_id, path = document.Name, metadata.RevisionId, document.FileName
        if cad.document_modified(document):
            raise workspace.WorkspaceError(
                "Save/upload the assembly before replacing a component revision"
            )
        yield from _editable(client, metadata)
        yield from _authorize_tree_labels(client, document)
        baseline = cad.capture_bom(document)
        by_name = {ref["object_name"]: ref for ref in baseline}
        selected_names = {
            obj.Name for obj in FreeCADGui.Selection.getSelection() if obj.Document is document
        }
        if selected_names - by_name.keys():
            raise workspace.WorkspaceError(
                "Select direct component links, not generated subassembly children"
            )
        groups = {}
        for ref in baseline:
            groups.setdefault((ref["target_item_id"], ref["target_revision_id"]), []).append(ref)
        if not groups:
            raise workspace.WorkspaceError(
                "This assembly has no supported direct component occurrences"
            )
        selected_groups = {
            key
            for key, refs in groups.items()
            if any(ref["object_name"] in selected_names for ref in refs)
        }
        if len(selected_groups) > 1:
            raise workspace.WorkspaceError(
                "Replace occurrences of one item and source revision at a time"
            )
        keys = list(groups)
        labels = [groups[key][0]["component_label"] for key in keys]
        if selected_groups:
            key = next(iter(selected_groups))
        else:
            value = ask_choice(
                "Replace Component Revision", "Choose the component to replace", labels
            )
            if value is None:
                return
            key = keys[labels.index(value)]
        matching = groups[key]
        rows = [
            dict(ref, occurrence_label=document.getObject(ref["object_name"]).Label)
            for ref in matching
        ]
        names = select_replacement_occurrences(rows, selected_names)
        if not names:
            return
        if set(names) - {ref["object_name"] for ref in matching}:
            raise workspace.WorkspaceError("The selected occurrences do not match the component")
        target_item = None
        if self.replace_any_item:
            query = ask_text(
                "Find Replacement Component", "Part or assembly number, name or description", ""
            )
            if query is None:
                return
            target_item = yield from _select_record(
                "Replacement Items",
                "Choose the replacement part or assembly",
                client.search_items,
                lambda row: "{} — {} ({})".format(row["number"], row["name"], row["kind"]),
                args=(query,),
            )
            if target_item is None:
                return
            if target_item["id"] == metadata.ItemId:
                raise workspace.WorkspaceError("An assembly cannot contain its own item")
            target_revision = yield from _select_record(
                "Replacement Revisions",
                "Choose the exact replacement revision",
                client.list_revisions,
                lambda row: "{} — {} — {}".format(
                    row["label"], row["lifecycle_state"], row["change_note"]
                ),
                args=(target_item["id"],),
            )
            if target_revision is None:
                return
            if target_revision["lifecycle_state"] == "obsolete":
                raise workspace.WorkspaceError("Choose a non-obsolete replacement revision")
        else:
            revisions = yield Request(
                "Loading newer component revisions…", client.newer_revisions, key
            )
            if not revisions:
                information(
                    "ForgePDM", "No newer non-obsolete revision is available for this component."
                )
                return
            revision_labels = [
                "{} — {} — {}".format(r["label"], r["lifecycle_state"], r["change_note"])
                for r in revisions
            ]
            choice = ask_choice(
                "New Component Revision",
                "Choose the exact replacement revision",
                revision_labels,
                revision_labels[0],
            )
            if choice is None:
                return
            target_revision = revisions[revision_labels.index(choice)]
        snapshot = yield from _choose_native_snapshot(client, target_revision["id"])
        if snapshot is None:
            return
        dataset, file_record = snapshot
        root = _choose_workspace(client, document)
        if root is None:
            return
        opened, applied = None, False
        try:
            configuration = yield Request(
                "Retrieving the chosen replacement snapshot…",
                client.retrieve_configuration,
                (root, target_revision["id"], dataset["id"], file_record["id"]),
            )
            opened = cad.open_configuration(configuration, _set_metadata)
            yield Request(
                "Recording verified replacement snapshot…",
                client.finish_configuration,
                (configuration,),
            )
            target_names = None
            if self.replace_any_item:
                target_names = _map_replacement_objects(document, baseline, names, opened["root"])
                if target_names is None:
                    return
                preview = [
                    "{} → {} ({})".format(
                        document.getObject(n).Label,
                        opened["root"].getObject(target_names[n]).Label,
                        target_names[n],
                    )
                    for n in names
                ]
                approved = review_component_replacement(
                    matching[0]["component_label"],
                    target_revision,
                    preview,
                    dataset["created_at"],
                    target_item["number"],
                )
            else:
                approved = review_component_replacement(
                    matching[0]["component_label"],
                    target_revision,
                    [document.getObject(n).Label for n in names],
                    dataset["created_at"],
                )
            if not approved:
                return
            document = _guard_document(name, revision_id)
            if (
                cad.document_modified(document)
                or document.FileName != path
                or cad.capture_bom(document) != baseline
            ):
                raise workspace.WorkspaceError(
                    "Assembly changed during review; prepare a new replacement"
                )
            yield from _editable(client, _require_metadata(document))
            yield from _authorize_tree_labels(client, document)
            document = _guard_document(name, revision_id)
            if (
                cad.document_modified(document)
                or document.FileName != path
                or cad.capture_bom(document) != baseline
            ):
                raise workspace.WorkspaceError("Assembly changed while rechecking checkout")
            yield Request(
                "Verifying original component snapshots…", client.validate_references, (matching,)
            )
            document = _guard_document(name, revision_id)
            if cad.document_modified(document) or cad.capture_bom(document) != baseline:
                raise workspace.WorkspaceError("Assembly changed while verifying references")
            if self.replace_any_item:
                count = replacement.apply(
                    document,
                    baseline,
                    names,
                    opened["root"],
                    target_revision,
                    target_names=target_names,
                )
            else:
                count = replacement.apply(
                    document, baseline, names, opened["root"], target_revision
                )
            applied = True
            FreeCAD.setActiveDocument(name)
            destination = (
                "{} revision {}".format(target_item["number"], target_revision["label"])
                if target_item
                else "revision {}".format(target_revision["label"])
            )
            information(
                "ForgePDM",
                "Replaced {} occurrence(s) with {}. Inspect geometry and joints, "
                "then save/upload and synchronize the BOM separately.".format(count, destination),
            )
        finally:
            if opened is not None and not applied:
                cad.close_owned(opened["owned"])
            try:
                if FreeCAD.getDocument(name) is not None:
                    FreeCAD.setActiveDocument(name)
            except NameError:
                pass


class ReplaceComponentCommand(ReplaceRevisionCommand):
    replace_any_item = True
    icon_name = "replace-component"
    menu_text = "Replace Component…"
    tooltip = "Search a part or assembly and explicitly map selected component occurrences"


def _map_replacement_objects(document, references, names, target_document):
    from . import replacement

    by_name = {ref["object_name"]: ref for ref in references}
    grouped = {}
    for name in names:
        grouped.setdefault(by_name[name]["target_object_name"], []).append(name)
    candidates = replacement.target_objects(target_document)
    mapping = {}
    for source_name, occurrences in grouped.items():
        objects = [
            obj
            for obj in candidates
            if obj.TypeId == "Assembly::AssemblyObject"
            or not any(
                document.getObject(n).TypeId == "Assembly::AssemblyLink" for n in occurrences
            )
        ]
        if not objects:
            raise workspace.WorkspaceError(
                "No compatible whole object is available in the replacement snapshot"
            )
        labels = ["{} ({}, {})".format(obj.Label, obj.Name, obj.TypeId) for obj in objects]
        default = next(
            (label for obj, label in zip(objects, labels) if obj.Name == source_name), labels[0]
        )
        choice = ask_choice(
            "Replacement Object",
            "Map {} ({} occurrence(s)) to".format(source_name, len(occurrences)),
            labels,
            default,
        )
        if choice is None:
            return None
        target = objects[labels.index(choice)]
        mapping.update({name: target.Name for name in occurrences})
    return mapping


def _choose_native_snapshot(client, revision_id):
    datasets = yield Request("Loading native CAD snapshots…", client.list_datasets, (revision_id,))
    choices = [
        (dataset, record)
        for dataset in datasets
        if dataset["dataset_type"] == "native_cad"
        for record in dataset["files"]
    ]
    if not choices:
        raise workspace.WorkspaceError("The chosen revision has no uploaded native CAD snapshot")
    if len(choices) == 1:
        return choices[0]
    labels = [
        "{}. {} — {} — {}".format(i + 1, ds["name"], ds["created_at"], rec["content_hash"][:8])
        for i, (ds, rec) in enumerate(choices)
    ]
    choice = ask_choice("CAD Snapshots", "Choose the exact saved snapshot", labels, labels[-1])
    return None if choice is None else choices[labels.index(choice)]


class ShowBOMCommand(Command):
    icon_name = "bom"
    menu_text = "Show ForgePDM BOM"
    tooltip = "Display the nested BOM or review and synchronize CAD occurrences"
    needs_document = True

    def action(self):
        client = Session.require_client()
        metadata = _require_metadata(_require_document())
        number, revision_id = metadata.ItemNumber, metadata.RevisionId
        lines = yield Request("Loading BOM…", client.get_bom, (revision_id,), {"recursive": True})
        updates = yield Request(
            "Checking newer component revisions…", client.bom_revision_updates, (lines,)
        )
        dialog = QtWidgets.QDialog(_main_window())
        dialog.setWindowTitle("ForgePDM BOM — " + number)
        dialog.resize(640, 480)
        layout = QtWidgets.QVBoxLayout(dialog)
        output = QtWidgets.QPlainTextEdit(dialog)
        output.setReadOnly(True)
        output.setPlainText(
            _format_bom(lines, updates=updates) or "This revision has no BOM lines."
        )
        layout.addWidget(output)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok, parent=dialog)
        buttons.accepted.connect(dialog.accept)
        synchronize = QtWidgets.QPushButton("Synchronize from CAD…")
        synchronize.clicked.connect(dialog.accept)
        requested = []
        synchronize.clicked.connect(lambda: requested.append(True))
        layout.addWidget(synchronize)
        layout.addWidget(buttons)
        execute_dialog(dialog)
        if requested:
            yield from _synchronize_bom(client, revision_id)


def _synchronize_bom(client, revision_id):
    document = _require_document()
    name = document.Name
    if _require_metadata(document).RevisionId != revision_id:
        raise RuntimeError("Select the original assembly before synchronizing its BOM")
    if cad.document_modified(document):
        raise RuntimeError("Save/upload the assembly before synchronizing its BOM")
    references = cad.capture_bom(document)
    path = document.FileName
    prepared = yield Request(
        "Verifying uploaded CAD occurrences…",
        client.prepare_cad_bom,
        (path, revision_id, references),
    )
    snapshot = yield Request("Loading editable BOM snapshot…", client.bom_snapshot, (revision_id,))
    selected = select_bom_occurrences(prepared["references"])
    if selected is None:
        return
    proposal = bom.propose_lines(
        {"profile": "freecad-app-link-v1", "references": prepared["references"]}, selected
    )
    if not review_bom(snapshot["lines"], proposal):
        return
    current = _guard_document(name, revision_id)
    if (
        cad.document_modified(current)
        or current.FileName != path
        or cad.capture_bom(current) != references
    ):
        raise RuntimeError("CAD occurrences changed during review. Prepare a new BOM proposal.")
    yield Request(
        "Synchronizing approved BOM…",
        client.synchronize_cad_bom,
        (
            path,
            revision_id,
            references,
            prepared["source_hash"],
            [line.as_payload() for line in proposal],
            snapshot,
        ),
        mutates=True,
        cancellable=False,
    )
    information("ForgePDM", "The reviewed engineering BOM was synchronized.")


class DownloadCommand(Command):
    icon_name = "download"
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


def _format_bom(lines, depth=0, updates=None):
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
        newer = (updates or {}).get(line.get("component_revision_id"))
        if newer:
            formatted[-1] += "  [Newer revision available: {}]".format(newer)
        children = _format_bom(line.get("children", []), depth + 1, updates)
        if children:
            formatted.append(children)
    return "\n".join(formatted)
