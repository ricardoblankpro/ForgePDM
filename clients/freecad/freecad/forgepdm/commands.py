"""FreeCAD Workbench commands backed by the ForgePDM HTTP API."""

import os
from pathlib import Path
from uuid import UUID

import FreeCAD
import FreeCADGui

from . import bom, cad, tree_labels, tree_observer, workspace
from .api import ForgePDMClient, ForgePDMError
from .i18n import translate
from .jobs import Request
from .resources import icon_path
from .session import Session
from .ui import (
    QtWidgets,
    ask_choice,
    ask_text,
    execute_dialog,
    information,
    review_bom,
    review_component_replacement,
    select_bom_occurrences,
    select_replacement_occurrences,
    warning,
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
        cad.settle_techdraw(document)
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
    cad.settle_techdraw(document)
    document.saveAs(path)
    cad.rebase_links(document)
    cad.settle_techdraw(document)
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
    yield from _prepare_description(client, document, metadata)
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
    return checkout


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


class RegisterStandardPartCommand(Command):
    icon_name = "upload"
    menu_text = "Register Standard / Purchased Part…"
    tooltip = "Create an S item without requiring a CAD document"

    def action(self):
        client = Session.require_client()
        item = yield from _register_standard(client)
        if item:
            choice = ask_choice(
                "Standard Part",
                "Metadata-only revision created. Next action?",
                ["Keep checked out", "Check in metadata", "Check in and release"],
                "Keep checked out",
            )
            if choice in ("Check in metadata", "Check in and release"):
                yield Request(
                    "Checking in metadata…",
                    client.checkin,
                    (item["current_revision_id"],),
                    mutates=True,
                )
            if choice == "Check in and release":
                yield Request(
                    "Releasing standard revision…",
                    client.transition,
                    (item["current_revision_id"], "released"),
                    mutates=True,
                )
            from .standard_mass import label

            mass = item.get("reference_mass") or {}
            suffix = (
                "\n{}: {} kg each.".format(label(mass), mass["mass_kg"])
                if mass.get("mass_kg") is not None
                else "\nSupplier reference mass unavailable."
                if item.get("reference_mass")
                else ""
            )
            information("ForgePDM", "Registered " + item["number"] + suffix)


def _standard_library_access(client):
    capability = yield Request(
        "Checking shared Standard Parts Library…", client.standard_capabilities
    )
    if not capability.get("shared_library"):
        raise workspace.WorkspaceError(
            "Update/restart the backend to use the shared Standard Parts Library"
        )
    if not capability.get("can_register"):
        raise workspace.WorkspaceError(
            "You have read-only Standard Parts Library access. Ask an administrator to grant library editor membership to register parts."
        )
    return capability


def _register_standard(client, spec=None, mass_object=None):
    capability = yield from _standard_library_access(client)
    manual = None
    if spec is not None:
        from .ui import standard_specification_dialog

        selected = standard_specification_dialog(spec["geometry"])
        if selected is None:
            return None
        if selected.get("manual_mass_g") is not None:
            if not capability.get("mass_fallback_version"):
                raise workspace.WorkspaceError(
                    "Update the backend before entering standard-part mass"
                )
            manual = selected
        spec, name, description = (
            selected["specification"],
            selected["name"],
            selected["description"],
        )
    else:
        # Generic purchased items have no Fasteners geometry/specification schema.
        name = ask_text("Register Standard Part", "Name / purchasing designation", "")
        if not name:
            return None
        description = ask_text("Register Standard Part", "Description (optional)", "")
        if description is None:
            return None
    item = yield Request(
        "Registering standard part…",
        client.create_item,
        ("part", name, None, description),
        kwargs={"number_series": "S", "standard_specification": spec},
        mutates=True,
        cancellable=False,
    )
    if capability.get("mass_fallback_version"):
        mass = yield from _enrich_standard_mass(
            client, item["current_revision_id"], mass_object, manual=manual
        )
        if mass is not None:
            item["reference_mass"] = mass
    return item


def _enrich_standard_mass(client, revision_id, obj=None, manual=None):
    """Optional enrichment must never invalidate a successful S registration."""
    from . import standard_mass

    if not hasattr(client, "lookup_reference_mass"):
        return None
    try:
        current = yield Request(
            "Looking up standard-part mass…",
            client.lookup_reference_mass,
            (revision_id,),
            mutates=True,
        )
        if not hasattr(client, "save_reference_mass"):
            return current
        if manual is not None and current.get("status") != "supplier_reference":
            payload = {
                "method": "manual",
                "mass_g": manual["manual_mass_g"],
                "note": manual.get("manual_mass_note", ""),
                "expected_token": current["token"],
            }
        else:
            payload = standard_mass.estimate(obj, current)
        if payload:
            current = yield Request(
                "Saving standard-part mass…",
                client.save_reference_mass,
                (revision_id, payload),
                mutates=True,
                cancellable=False,
            )
        return current
    except (ForgePDMError, ValueError, AttributeError, ReferenceError, RuntimeError) as error:
        # Geometry/provider/checkout failures leave the engineering operation intact.
        console = getattr(FreeCAD, "Console", None)
        if console is not None and hasattr(console, "PrintWarning"):
            console.PrintWarning(
                "ForgePDM: mass remains unavailable or unchanged: {}\n".format(error)
            )
        return None


class ChangeStandardPartAssociationCommand(Command):
    icon_name = "replace-component"
    menu_text = "Change Standard Part Association…"
    tooltip = "Choose another S specification for selected fasteners without moving them"
    needs_document = True

    def action(self):
        from . import fasteners

        client = Session.require_client()
        document = _require_document()
        metadata = _require_metadata(document)
        name, revision_id = document.Name, metadata.RevisionId
        selection = list(FreeCADGui.Selection.getSelection())
        if not selection or any(
            obj.Document is not document or not fasteners.recognized(obj) for obj in selection
        ):
            raise workspace.WorkspaceError(
                "Select one or more direct Fasteners Workbench objects in the active assembly"
            )
        selected_names = {obj.Name for obj in selection}
        revision = yield from _editable(client, metadata)
        if revision["item_kind"] != "assembly":
            raise workspace.WorkspaceError("Standard part reassociation requires an assembly")
        yield from _authorize_tree_labels(client, document)
        document = _guard_document(name, revision_id)
        if document.HasPendingTransaction:
            raise workspace.WorkspaceError(
                "Finish the current FreeCAD operation before changing associations"
            )
        if not (yield from _associate_fasteners(client, document, selected_names=selected_names)):
            return
        information(
            "ForgePDM",
            "Selected standard part associations updated. Upload the assembly, then review BOM synchronization. Geometry and attachments were preserved.",
        )


def _associate_fasteners(client, document, selected_names=None):
    from . import fasteners
    from .standard_contract import encode

    all_candidates = fasteners.objects(document)
    candidates = (
        all_candidates
        if selected_names is None
        else [obj for obj in all_candidates if obj.Name in selected_names]
    )
    if selected_names is not None and {obj.Name for obj in candidates} != set(selected_names):
        raise workspace.WorkspaceError(
            "Selected fasteners changed or disappeared; select them again"
        )
    if not candidates:
        return True
    document.recompute()
    cad._builtin_bom_context(document)
    for obj in candidates:
        cad.validate_fastener_membership(document, obj)
        fasteners.attachment(obj)
    capability = yield Request("Checking Fasteners integration…", client.standard_capabilities)
    if capability.get("version") != 1 or not capability.get("snapshot_evidence"):
        raise workspace.WorkspaceError("Update the backend for Fasteners integration")
    name = document.Name
    revision_id = _require_metadata(document).RevisionId if selected_names is not None else None

    def baseline_state():
        current = fasteners.objects(document)
        if selected_names is not None:
            current = [obj for obj in current if obj.Name in selected_names]
        return [
            (obj.Name, fasteners.extract(obj), getattr(obj, fasteners.ASSOCIATION, ""))
            for obj in current
        ]

    baseline = baseline_state()
    groups, retained, seen, identities = {}, [], set(), {}
    if selected_names is not None:
        for obj in all_candidates:
            if obj.Name not in selected_names:
                entry = fasteners.association(obj)
                if entry:
                    seen.add(entry["occurrence_id"])
    for obj in candidates:
        entry = fasteners.association(obj)
        if selected_names is not None:
            if entry and entry["occurrence_id"] not in seen:
                identities[obj.Name] = entry["occurrence_id"]
                seen.add(entry["occurrence_id"])
            entry = None
        if entry:
            revision = yield Request(
                "Validating standard association…", client.get_revision, (entry["revision_id"],)
            )
            if revision["lifecycle_state"] == "obsolete":
                entry = None
        if entry:
            identifier = entry["occurrence_id"] if entry["occurrence_id"] not in seen else None
            if identifier:
                seen.add(identifier)
            retained.append((obj.Name, entry["revision_id"], identifier))
        else:
            groups.setdefault(encode(fasteners.extract(obj)), []).append(obj.Name)
    resolved = list(retained)
    for key, names in groups.items():
        import json

        geometry = json.loads(key)
        matches = yield Request("Finding catalog fasteners…", client.standard_matches, (geometry,))
        choices = [
            row["number"]
            + " — "
            + row["name"]
            + " — Rev "
            + row["revision_label"]
            + " — "
            + fasteners.describe(row["specification"])
            for row in matches["items"]
        ]
        selected = ask_choice(
            "Associate Fasteners",
            "{} occurrence(s): {}. Confirm the full purchasing specification.".format(
                len(names), fasteners.describe(geometry)
            ),
            choices + ["Register a new S item"],
            choices[0] if choices else "Register a new S item",
        )
        if selected is None:
            return False
        if selected == "Register a new S item":
            item = yield from _register_standard(
                client, dict(geometry=geometry), mass_object=document.getObject(names[0])
            )
            if item is None:
                return False
            information(
                "ForgePDM",
                "Registered {}. This item remains available even if assembly upload is canceled.".format(
                    item["number"]
                ),
            )
        else:
            item = matches["items"][choices.index(selected)]
        resolved.extend(
            (obj_name, item["current_revision_id"], identities.get(obj_name)) for obj_name in names
        )
    # Include retained associations: older Working S entries can gain estimates
    # without changing their identity, placement or CAD association metadata.
    measured = set()
    for object_name, target_revision, _occurrence in resolved:
        if target_revision in measured:
            continue
        measured.add(target_revision)
        mass = yield from _enrich_standard_mass(
            client, target_revision, document.getObject(object_name)
        )
        if mass and mass.get("mass_kg") is not None:
            from .standard_mass import label

            FreeCAD.Console.PrintMessage(
                "ForgePDM: {} kg each ({}).\n".format(mass["mass_kg"], label(mass))
            )
    document = (
        _guard_document(name, revision_id) if selected_names is not None else _guard_document(name)
    )
    if selected_names is not None:
        yield from _editable(client, _require_metadata(document))
        yield from _authorize_tree_labels(client, document)
        document = _guard_document(name, revision_id)
        if document.HasPendingTransaction:
            raise workspace.WorkspaceError(
                "Finish the current FreeCAD operation before changing associations"
            )
    if baseline_state() != baseline:
        raise workspace.WorkspaceError("Fasteners changed during association; retry upload")
    document.openTransaction("Associate ForgePDM standard parts")
    try:
        for obj_name, revision_id, occurrence_id in resolved:
            obj = document.getObject(obj_name)
            old = fasteners.association(obj)
            if (
                not old
                or old["revision_id"] != revision_id
                or old["occurrence_id"] != occurrence_id
            ):
                fasteners.associate(obj, revision_id, occurrence_id)
        document.commitTransaction()
    except BaseException:
        document.abortTransaction()
        raise
    return True


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
            kind = ask_choice(
                "New ForgePDM Item",
                "Item kind",
                ["part", "assembly", "standard/purchased part"],
                "part",
            )
            if not kind:
                return
            if kind == "standard/purchased part":
                yield from _standard_library_access(client)
                project = {"id": None}
            else:
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
        if not (yield from _associate_fasteners(client, document)):
            return
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
                (
                    "part" if kind == "standard/purchased part" else kind,
                    document.Label,
                    project.get("id"),
                ),
                kwargs={"number_series": "S"} if kind == "standard/purchased part" else {},
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
        revision = yield Request(
            "Inspecting check-in revision…", client.get_revision, (revision_id,)
        )
        if revision["item_id"] != metadata.ItemId:
            raise workspace.WorkspaceError("Document item/revision metadata is inconsistent")
        actor_id = (Session.user or {}).get("id")
        if revision["item_kind"] in ("part", "assembly"):
            try:
                recovered = yield Request(
                    "Resolving previous check-in…",
                    client.resume_part_checkin,
                    (document.FileName, revision_id, metadata.ItemId, actor_id),
                    mutates=True,
                )
            except ForgePDMError as error:
                if error.status != 409:
                    raise
                choice = ask_choice(
                    "Interrupted Check-in",
                    "The previous operation has a stale checkout. Keep its snapshot, or start a new operation from the current document?",
                    ["Keep pending snapshot", "Start new check-in from current document"],
                    "Keep pending snapshot",
                )
                if choice != "Start new check-in from current document":
                    return
                yield Request(
                    "Archiving the uncommitted snapshot…",
                    client.abandon_part_checkin,
                    (document.FileName, revision_id, metadata.ItemId, actor_id),
                    cancellable=False,
                )
                recovered = None
            if recovered is not None:
                tree_observer.revoke_revision(revision_id)
                if recovered.get("local_changes_remain") or cad.document_modified(document):
                    warning(
                        "ForgePDM",
                        "The previous snapshot is checked in. Local edits remain and were not included; acquire a checkout before uploading them.",
                    )
                else:
                    information(
                        "ForgePDM",
                        "The previous check-in was confirmed. No duplicate dataset was created.",
                    )
                return
        yield from _editable(client, metadata)
        if not (yield from _associate_fasteners(client, document)):
            return
        references = cad.capture(document)
        path = yield from _ensure_working(client, document)
        if path is None:
            return
        document = _guard_document(document.Name, revision_id)
        if cad.capture(document) != references:
            raise workspace.WorkspaceError(
                "CAD references changed; review the document before retrying"
            )
        yield from _authorize_tree_labels(client, document)
        tree_labels.refresh(document)
        yield from _prepare_description(client, document, metadata)
        _save_document(document)
        result = yield Request(
            "Checking in verified CAD snapshot…",
            client.checkin_part,
            (path, revision_id, metadata.ItemId, actor_id, references),
            mutates=True,
        )
        tree_observer.revoke_revision(revision_id)
        if result.get("local_changes_remain") or cad.document_modified(document):
            warning(
                "ForgePDM",
                "The snapshot was checked in. Local edits remain and were not included.",
            )
        else:
            information("ForgePDM", "CAD snapshot checked in atomically")
        return


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
    update_snapshot = False
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
        by_name = {
            ref["object_name"]: ref
            for ref in baseline
            if ref.get("property_name", "LinkedObject") == "LinkedObject"
        }
        selected_names = {
            obj.Name for obj in FreeCADGui.Selection.getSelection() if obj.Document is document
        }
        if selected_names - by_name.keys():
            raise workspace.WorkspaceError(
                "Select direct component links, not generated subassembly children"
            )
        groups = {}
        for ref in baseline:
            if ref.get("property_name", "LinkedObject") != "LinkedObject":
                continue
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
        update = None
        if self.update_snapshot:
            chosen = [ref for ref in matching if ref["object_name"] in names]
            update = yield Request(
                "Checking selected component snapshots…",
                client.prepare_component_update,
                (path, metadata.ItemId, revision_id, chosen),
            )
            names = update["names"]
            if not names:
                information(
                    "ForgePDM",
                    "Selected occurrences already use the latest uploaded snapshot of this revision.",
                )
                return
            target_revision = update["revision"]
        elif self.replace_any_item:
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
        snapshot = (
            (update["dataset"], update["file"])
            if update is not None
            else (yield from _choose_native_snapshot(client, target_revision["id"]))
        )
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
            elif self.update_snapshot:
                pins = {pin["object_name"]: pin for pin in update["pins"]}
                approved = review_component_replacement(
                    matching[0]["component_label"],
                    target_revision,
                    [
                        "{}: {}/{} → {}/{}".format(
                            document.getObject(n).Label,
                            pins[n]["target_dataset_id"],
                            pins[n]["target_file_id"],
                            dataset["id"],
                            file_record["id"],
                        )
                        for n in names
                    ],
                    "{} — SHA-256 {}".format(dataset["created_at"], file_record["content_hash"]),
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
            checkout = yield from _authorize_tree_labels(client, document)
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
            if self.update_snapshot:
                current_parent = yield Request(
                    "Rechecking assembly snapshot…",
                    client.component_update_baseline,
                    (path, metadata.ItemId, revision_id, matching),
                )
                document = _guard_document(name, revision_id)
                pins = {pin["object_name"]: pin for pin in current_parent["pins"]}
                if (
                    current_parent["baseline"] != update["baseline"]
                    or any(pins.get(pin["object_name"]) != pin for pin in update["pins"])
                    or document.FileName != path
                    or cad.document_modified(document)
                    or cad.capture_bom(document) != baseline
                ):
                    raise workspace.WorkspaceError(
                        "Assembly or component snapshots changed during review"
                    )
                tree_observer.allow_edit(document, checkout, client, Session.user)
                exact_baseline = [
                    dict(ref, **pins[ref["object_name"]]) if ref["object_name"] in pins else ref
                    for ref in baseline
                ]
                count = replacement.apply(
                    document,
                    exact_baseline,
                    names,
                    opened["root"],
                    target_revision,
                    target_snapshot=dict(dataset_id=dataset["id"], file_id=file_record["id"]),
                )
            elif self.replace_any_item:
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


class UpdateSelectedComponentsCommand(ReplaceRevisionCommand):
    update_snapshot = True
    icon_name = "replace-revision"
    menu_text = "Update Selected Components from Server…"
    tooltip = "Review and adopt the latest uploaded snapshot of selected component occurrences"


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


class PublishDrawingsCommand(Command):
    icon_name = "publish-drawings"
    menu_text = "Publish Drawing PDFs…"
    tooltip = "Publish reviewed TechDraw PDFs from this exact uploaded CAD snapshot"
    needs_document = True

    def action(self):
        from . import drawing_export
        from .ui import review_drawing_publication, select_drawing_pages

        client = Session.require_client()
        document = _require_document()
        metadata = _require_metadata(document)
        name, path = document.Name, document.FileName
        revision_id, item_id = metadata.RevisionId, metadata.ItemId
        actor_id = (Session.user or {}).get("id")
        args = (path, revision_id, item_id, actor_id)
        try:
            recovered = yield Request(
                "Recovering previous drawing publication…",
                client.resume_drawings,
                args,
                mutates=True,
            )
        except ForgePDMError as error:
            if error.status != 409:
                raise
            choice = ask_choice(
                "Pending Drawing Publication",
                "The prior publication has a stale checkout. Keep its frozen PDFs, or start a new reviewed publication?",
                ["Keep pending publication", "Start a new reviewed publication"],
                "Keep pending publication",
            )
            if choice != "Start a new reviewed publication":
                return
            yield Request(
                "Archiving prior drawing intent…", client.abandon_drawings, args, cancellable=False
            )
            recovered = None
        if recovered is not None:
            information(
                "ForgePDM",
                "The previous drawing publication was confirmed without duplicate PDFs. Current CAD edits were preserved.",
            )
            return

        def guard():
            current = _guard_document(name, revision_id)
            if (
                current.FileName != path
                or _require_metadata(current).ItemId != item_id
                or cad.document_modified(current)
            ):
                raise workspace.WorkspaceError(
                    "Save/upload the source document before publishing drawing PDFs"
                )
            return current

        document = guard()
        candidates = [
            dict(
                page_name=obj.Name,
                page_label=obj.Label,
                filename="{}-{}-{}.pdf".format(
                    metadata.ItemNumber, metadata.RevisionLabel, obj.Name
                ),
            )
            for obj in document.Objects
            if obj.isDerivedFrom("TechDraw::DrawPage")
        ]
        if not candidates:
            raise workspace.WorkspaceError("This document has no TechDraw pages")
        selected = select_drawing_pages(candidates)
        if not selected:
            return
        if len(selected) > 32 or any(page not in candidates for page in selected):
            raise workspace.WorkspaceError("Select between 1 and 32 pages from the active document")
        plan = yield Request(
            "Verifying drawing source and checkout…", client.prepare_drawings, args
        )
        guard()
        if not review_drawing_publication(plan, selected):
            return
        configuration, finished = None, False
        try:
            configuration = yield Request(
                "Retrieving verified PDF source configuration…",
                client.retrieve_configuration,
                (
                    plan["root"],
                    revision_id,
                    plan["intent"]["source_dataset_id"],
                    plan["intent"]["source_file_id"],
                ),
            )
            guard()
            pages = drawing_export.export(configuration, selected, plan["directory"], _set_metadata)
            guard()
            yield Request(
                "Recording PDF source configuration…", client.finish_configuration, (configuration,)
            )
            finished = True
            yield Request(
                "Freezing reviewed PDF publication…",
                client.freeze_drawings,
                (plan, pages),
                cancellable=False,
            )
            guard()
            result = yield Request(
                "Publishing drawing PDFs…", client.resume_drawings, args, mutates=True
            )
            information(
                "ForgePDM",
                "Published {} drawing PDF(s) for this exact CAD snapshot. View them in the web GUI's Drawings tab. Your checkout is retained.".format(
                    len(result["pages"])
                ),
            )
        finally:
            if configuration is not None and not finished:
                workspace.incomplete(configuration)


class RefreshPDMStatusCommand(Command):
    icon_name = "tree-status"
    menu_text = "Refresh PDM Status"
    tooltip = "Show checkout owners, lifecycle and available server updates in the tree"
    needs_document = True

    def Activated(self):
        try:
            Session.require_client()
        except RuntimeError as error:
            warning("ForgePDM", str(error))
            return
        from . import tree_status

        tree_status.enable().request()


class UpdateFromServerCommand(Command):
    icon_name = "download"
    menu_text = "Update from Server…"
    tooltip = "Check for uploaded changes and open a verified copy of this revision"
    needs_document = True

    def action(self):
        client = Session.require_client()
        document = _require_document()
        metadata = _require_metadata(document)
        name, path = document.Name, document.FileName
        item_id, revision_id = metadata.ItemId, metadata.RevisionId

        def guard():
            current = _guard_document(name, revision_id)
            if current.FileName != path or cad.document_modified(current):
                raise workspace.WorkspaceError(
                    "Local document changed. Save/upload or preserve your edits before updating."
                )
            if _require_metadata(current).ItemId != item_id:
                raise workspace.WorkspaceError("Document item changed while checking updates")
            return current

        guard()
        result = yield Request(
            "Checking uploaded server snapshots…",
            client.inspect_server_update,
            (path, item_id, revision_id),
        )
        guard()
        newer = result["newer"]
        notice = (
            "\nNewer revisions available: {}. Adopt these explicitly using revision replacement.".format(
                ", ".join(row["label"] for row in newer)
            )
            if newer
            else ""
        )
        if not result["changed"]:
            information(
                "ForgePDM",
                "This document already uses the latest uploaded snapshot of this revision."
                + notice,
            )
            return
        dataset, record = result["dataset"], result["file"]
        choice = ask_choice(
            "Update from Server",
            "{} revision {}: snapshot {} ({}).\nOpen a separate verified copy? "
            "The original document and existing assembly links are preserved.{}".format(
                metadata.ItemNumber,
                metadata.RevisionLabel,
                dataset["created_at"],
                record["content_hash"][:12],
                notice,
            ),
            ["Cancel", "Open updated copy"],
            "Cancel",
        )
        if choice != "Open updated copy":
            return
        guard()
        configuration, opened, complete = None, None, False
        try:
            configuration = yield Request(
                "Retrieving reviewed server snapshot…",
                client.retrieve_configuration,
                (result["baseline"]["root"], revision_id, dataset["id"], record["id"]),
            )
            guard()
            current = yield Request(
                "Rechecking local snapshot…",
                client.update_baseline,
                (path, item_id, revision_id),
            )
            guard()
            if current != result["baseline"]:
                raise workspace.WorkspaceError("Local snapshot changed during update; retry review")
            opened = cad.open_configuration(configuration, _set_metadata)
            yield Request(
                "Recording updated configuration…",
                client.finish_configuration,
                (configuration,),
            )
            complete = True
            FreeCAD.setActiveDocument(opened["root"].Name)
            information(
                "ForgePDM",
                "Updated copy opened. The original remains open and unchanged. "
                "Existing assembly links keep their exact snapshots. "
                "Acquire a checkout on the updated copy before editing.",
            )
        finally:
            if not complete:
                if opened is not None:
                    cad.close_owned(opened["owned"])
                if configuration is not None:
                    workspace.incomplete(configuration)
                try:
                    FreeCAD.setActiveDocument(name)
                except (NameError, RuntimeError):
                    pass


class DownloadCommand(Command):
    icon_name = "download"
    menu_text = "Download Item / Assembly"
    tooltip = "Search items and retrieve a selected revision"

    def action(self):
        client = Session.require_client()
        series = ask_choice(
            "Catalog",
            "Browse which items?",
            ["All items", "Standard / purchased parts"],
            "All items",
        )
        if series is None:
            return
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
            kwargs={"number_series": "S"} if series == "Standard / purchased parts" else {},
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


def _prepare_description(client, document, metadata):
    if not getattr(metadata, "ItemNumber", "").startswith(("P", "A")):
        return
    from . import descriptions

    name, revision_id = document.Name, metadata.RevisionId
    current = yield Request("Reading revision description…", client.get_description, (revision_id,))
    document = _guard_document(name, revision_id)
    metadata = _require_metadata(document)
    descriptions.prepare(document, metadata, current)
    if getattr(metadata, "ItemNumber", "").startswith("P"):
        from . import physical_materials

        document.recompute()
        physical_materials.refresh(document, metadata)


class AssignMaterialsCommand(Command):
    menu_text = "Assign Material / Set Description…"
    tooltip = "Select an M material for a part or enter an assembly description"
    needs_document = True

    def action(self):
        from . import descriptions, tree_status

        client = Session.require_client()
        document = _require_document()
        metadata = _require_metadata(document)
        yield from _editable(client, metadata)
        yield from _authorize_tree_labels(client, document)
        name, revision_id = document.Name, metadata.RevisionId
        series = metadata.ItemNumber[:1]
        if series not in ("P", "A"):
            raise ValueError("Select a managed P part or A assembly")
        current = yield Request("Reading description…", client.get_description, (revision_id,))
        description, material_id = current["description"], current["material_revision_id"]
        physical = None
        if series == "A":
            description = ask_text("Assembly description", "Description", description)
            if description is None:
                return
            material_id = None
        else:
            choice = ask_choice(
                "Part material",
                "Action",
                ["Select material", "Clear material", "Cancel"],
                "Select material",
            )
            if not choice or choice == "Cancel":
                return
            if choice == "Clear material":
                description, material_id = "", None
            else:
                record = yield from _select_record(
                    "Materials",
                    "Choose raw material",
                    client.search_items,
                    lambda r: r["number"] + " — " + r["name"],
                    kwargs={"number_series": "M"},
                )
                if not record:
                    return
                selected = yield Request(
                    "Checking selected material…",
                    client.get_revision,
                    (record["current_revision_id"],),
                )
                material = yield Request(
                    "Reading material description…", client.get_description, (selected["id"],)
                )
                description, material_id = material["description"], selected["id"]
                physical = material.get("physical_material")
                if not description or selected["lifecycle_state"] == "obsolete":
                    raise ValueError("Select a usable material with a description")
        document = _guard_document(name, revision_id)
        yield from _editable(client, _require_metadata(document))
        yield from _authorize_tree_labels(client, document)
        descriptions.apply(
            document,
            _require_metadata(document),
            current,
            description.strip(),
            material_id,
            physical,
        )
        tree_status.enable().request()
        information("ForgePDM", "Description applied. Upload or Check In to publish it.")


def _physical_capability(client):
    value = yield Request("Checking physical-material support…", client.physical_capabilities)
    if value.get("physical_material_version") != 1:
        raise ValueError(
            "Update/restart the backend before registering or linking physical materials"
        )


class RegisterRawMaterialCommand(Command):
    menu_text = "Register Raw Material…"
    tooltip = "Register an M description linked to a FreeCAD physical material"

    def action(self):
        from . import physical_materials

        client = Session.require_client()
        yield from _standard_library_access(client)
        yield from _physical_capability(client)
        result = physical_materials.registration_dialog()
        if result is None:
            return
        description, physical = result
        item = yield Request(
            "Registering raw material…",
            client.create_item,
            ("part", description[:200]),
            kwargs={
                "description": description,
                "number_series": "M",
                "physical_material": physical,
            },
            mutates=True,
            cancellable=False,
        )
        information(
            "ForgePDM",
            "Registered " + item["number"] + ". The physical material and density are linked.",
        )


class LinkPhysicalMaterialCommand(Command):
    menu_text = "Link Physical Material…"
    tooltip = "Link an existing M catalog entry to a FreeCAD physical material"

    def action(self):
        from . import physical_materials

        client = Session.require_client()
        yield from _standard_library_access(client)
        yield from _physical_capability(client)
        item = yield from _select_record(
            "Raw materials",
            "Choose M entry",
            client.search_items,
            lambda r: r["number"] + " — " + r["name"],
            kwargs={"number_series": "M"},
        )
        if item is None:
            return
        revision = yield Request(
            "Reading material revision…", client.get_revision, (item["current_revision_id"],)
        )
        if revision["lifecycle_state"] == "obsolete":
            raise ValueError("Choose a usable M revision")
        description = yield Request(
            "Reading material description…", client.get_description, (revision["id"],)
        )
        existing = yield Request(
            "Reading physical link…", client.get_physical_link, (revision["id"],)
        )
        choice = physical_materials.registration_dialog(description["description"])
        if choice is None:
            return
        if revision["lifecycle_state"] == "released":
            if (
                ask_choice(
                    "New material revision",
                    "Create a new revision to link this Released material?",
                    ["Create revision", "Cancel"],
                    "Cancel",
                )
                != "Create revision"
            ):
                return
            revision = yield Request(
                "Creating material revision…",
                client.create_next_revision,
                (item["id"], "Link physical material"),
                mutates=True,
                cancellable=False,
            )
            existing = yield Request(
                "Reading copied physical link…", client.get_physical_link, (revision["id"],)
            )
        lease = yield Request("Checking material checkout…", client.get_checkout, (revision["id"],))
        if lease and lease["user_id"] != (Session.user or {}).get("id"):
            raise ValueError("The material is checked out by another user")
        if not lease:
            yield Request(
                "Acquiring material checkout…",
                client.acquire_checkout,
                (revision["id"],),
                mutates=True,
            )
        yield Request(
            "Linking physical material…",
            client.link_physical_material,
            (revision["id"], choice[1], existing["token"]),
            mutates=True,
            cancellable=False,
        )
        information(
            "ForgePDM",
            "Physical material linked. Existing part revisions keep their previous assignment; select this material again to adopt the link.",
        )
