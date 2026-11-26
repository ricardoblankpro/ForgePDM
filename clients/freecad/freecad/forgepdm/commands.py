"""FreeCAD Workbench commands backed by the ForgePDM HTTP API."""

import os
from pathlib import Path
from uuid import UUID

import FreeCAD
import FreeCADGui

from . import bom, cad, thumbnail_render, tree_labels, tree_observer, workspace
from .api import ForgePDMClient, ForgePDMError
from .i18n import translate
from .jobs import Request
from .mass_display import format_mass
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
        if (
            tree_observer.can_edit(document)
            and len([o for o in document.Objects if o.TypeId == "Assembly::AssemblyObject"]) == 1
        ):
            from . import insertion

            insertion.assign_member_ids(document)
        document.recompute()
        cad.settle_techdraw(document)
        if save_as:
            document.saveAs(path)
        else:
            document.save()
        # Native Save As can retain cached paths relative to the old folder.
        # Refresh on ordinary saves too, to recover copies moved earlier.
        if cad.repair_saved_link_paths(document):
            cad.settle_techdraw(document)
            document.save()
    except (OSError, RuntimeError) as exception:
        raise RuntimeError(
            "Could not save FreeCAD document to '{}': {}. "
            "Choose a writable location using File > Save As and try again.".format(path, exception)
        ) from exception
    saved_path = os.path.abspath(document.FileName)
    if not os.path.isfile(saved_path):
        raise RuntimeError("FreeCAD did not create the saved file: '{}'".format(saved_path))
    if getattr(document, "HasPendingTransaction", False) and tree_observer.can_edit(document):
        control = getattr(FreeCADGui, "Control", None)
        if control is None or not control.activeDialog():
            document.commitTransaction()
    if tree_observer.can_edit(document):
        metadata = _require_metadata(document)
        server = getattr(metadata, "ServerUrl", "") or Session.client.base_url
        value = workspace.working_path(saved_path, server)
        if value is not None:
            entry = value["entry"]
            if (
                entry.get("item_id", metadata.ItemId) != metadata.ItemId
                or entry.get("revision_id", metadata.RevisionId) != metadata.RevisionId
            ):
                raise workspace.WorkspaceError(
                    "Working-copy identity differs from the saved document"
                )
            with workspace.locked(value["root"], server):
                entry.update(
                    item_id=metadata.ItemId,
                    revision_id=metadata.RevisionId,
                    item_number=metadata.ItemNumber,
                    revision_label=metadata.RevisionLabel,
                    saved_hash=workspace.digest(saved_path)[0],
                    workspace_record_version=2,
                )
                workspace._atomic_json(value["directory"] / workspace.MANIFEST, value["ledger"])
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


def _current_action(action):
    """FreeCAD can retain a Python command instance across a live module reload."""
    owner = getattr(action, "__self__", None)
    previous = type(owner)
    current = globals().get(previous.__name__)
    if (
        previous.__module__ == __name__
        and isinstance(current, type)
        and issubclass(current, Command)
        and current is not previous
    ):
        # Retain instance attributes and the existing toolbar/menu registration.
        # Re-adding the same command ID does not replace every retained callback.
        try:
            owner.__class__ = current
        except TypeError as error:
            raise RuntimeError(
                "Save your work and restart FreeCAD to finish updating ForgePDM"
            ) from error
        return getattr(owner, action.__name__)
    return action


def _run(action):
    from .tasks import run

    return run(_current_action(action)())


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


def _configured_workspace(client):
    from . import settings

    user = Session.user or {}
    root = settings.workspace_root(client.base_url, user.get("id"))
    if not root:
        # Adopt the previous global folder only for the account it was saved with.
        preferences = settings.load()
        if preferences["url"].rstrip("/") == client.base_url and preferences[
            "username"
        ] == user.get("username"):
            root = settings.workspace_root()
    return root


def _choose_workspace(client, document=None, force=False):
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
    from .open_model import validate_workspace

    configured = _configured_workspace(client)
    if configured and not force:
        try:
            root = validate_workspace(configured, client.base_url)
        except workspace.WorkspaceError:
            pass
        else:
            settings.save_workspace(root, client.base_url, (Session.user or {}).get("id"))
            return root
    selected = QtWidgets.QFileDialog.getExistingDirectory(
        _main_window(),
        "Choose ForgePDM workspace",
        configured or os.path.expanduser("~"),
    )
    if not selected:
        return None
    selected = validate_workspace(selected, client.base_url)
    settings.save_workspace(selected, client.base_url, (Session.user or {}).get("id"))
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
    preview = thumbnail_render.optional(document)
    result = yield Request(
        "Uploading verified native CAD snapshot…",
        client.upload_native,
        (path, metadata.RevisionId, metadata.ItemId, references, preview),
        mutates=True,
    )
    if result.get("thumbnail_warning") or preview is None:
        warning(
            "ForgePDM",
            result.get("thumbnail_warning")
            or "CAD uploaded successfully; its preview is unavailable.",
        )
    if result.get("local_changes_remain") or document.isTouched():
        warning(
            "ForgePDM",
            "The saved snapshot was uploaded, but local changes remain. They were not included in that upload.",
        )
    return result


def _authorize_tree_labels(client, document, allow_staging=False):
    metadata = _require_metadata(document)
    value = workspace.working_path(document.FileName, client.base_url)
    if value is not None and value["entry"].get("publication_staging") and not allow_staging:
        raise workspace.WorkspaceError(
            "This document is a publication copy. Activate the original editable working document."
        )
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
    managed_document = True
    number_series = ()

    def GetResources(self):
        return {
            "Pixmap": icon_path(self.icon_name),
            "MenuText": translate("ForgePDM", self.menu_text),
            "ToolTip": translate("ForgePDM", self.tooltip),
        }

    def IsActive(self):
        if Session.busy or Session.client is None:
            return False
        if not self.needs_document:
            return True
        document = FreeCAD.ActiveDocument
        if document is None:
            return False
        if not self.managed_document:
            return True
        metadata = _metadata(document)
        return bool(
            metadata
            and getattr(metadata, "ItemId", "")
            and getattr(metadata, "RevisionId", "")
            and (
                not self.number_series
                or getattr(metadata, "ItemNumber", "").startswith(self.number_series)
            )
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
    icon_name = "standard-part"
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
                "\n{}: {} kg each.".format(label(mass), format_mass(mass["mass_kg"]))
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


def _source_language(client):
    if not hasattr(client, "description_proposal"):
        return True
    choice = ask_choice(
        "Description language",
        "Original language for the new item",
        ["English (en)", "Português (pt-BR)"],
        "English (en)",
    )
    if choice is None:
        return False
    client.creation_language = "pt-BR" if "pt-BR" in choice else "en"
    return True


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
    if not _source_language(client):
        return None
    if spec is not None and hasattr(client, "description_proposal"):
        try:
            proposal = yield Request(
                "Preparing purchasing designation…",
                client.description_proposal,
                (spec, client.creation_language),
            )
            decision = ask_choice(
                "Review purchasing description",
                proposal["text"],
                ["Register", "Cancel"],
                "Register",
            )
            if decision != "Register":
                return None
            name = description = proposal["text"]
        except ForgePDMError as error:
            if error.status not in (404, 422):
                raise
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
    number_series = ("A",)
    icon_name = "associate-fastener"
    menu_text = "Change Standard Part Association…"
    tooltip = "Choose another S specification for selected fasteners without moving them"
    needs_document = True

    def IsActive(self):
        if not super().IsActive():
            return False
        from . import fasteners

        selection = FreeCADGui.Selection.getSelection()
        return bool(selection) and all(
            obj.Document is FreeCAD.ActiveDocument and fasteners.recognized(obj)
            for obj in selection
        )

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
                "ForgePDM: {} kg each ({}).\n".format(format_mass(mass["mass_kg"]), label(mass))
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
    managed_document = False
    icon_name = "upload"
    menu_text = "Create / Upload…"
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
            if not _source_language(client):
                return
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
    menu_text = "Check Out / Renew"
    tooltip = "Acquire or extend the active revision checkout"
    needs_document = True

    def action(self):
        client = Session.require_client()
        document = _require_document()
        metadata = _require_metadata(document)
        name, revision_id = document.Name, metadata.RevisionId
        existing = (
            workspace.working_path(document.FileName, client.base_url)
            if document.FileName
            else None
        )
        if existing is not None and existing["entry"].get("publication_staging"):
            raise workspace.WorkspaceError(
                "Activate the original editing document; this copy belongs to publication recovery"
            )
        result = yield Request(
            "Acquiring checkout…",
            client.acquire_checkout,
            (revision_id,),
            mutates=True,
            cancellable=False,
        )
        document = _guard_document(name, revision_id)
        if workspace.working_path(document.FileName, client.base_url) is None:
            if cad.document_modified(document):
                raise workspace.WorkspaceError(
                    "Checkout acquired. Preserve unsaved edits before opening a separate working copy."
                )
            references = cad.capture(document)
            path = yield Request(
                "Preparing separate editable document…",
                client.fork_working,
                (document.FileName, references),
            )
            document = FreeCAD.openDocument(path)
            FreeCAD.setActiveDocument(document.Name)
            document.Label = metadata.ItemNumber + "-" + metadata.RevisionLabel
        else:
            path = _save_document(document)
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
                if recovered.get("thumbnail_warning"):
                    warning("ForgePDM", recovered["thumbnail_warning"])
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
        preview = thumbnail_render.optional(document)
        result = yield Request(
            "Checking in verified CAD snapshot…",
            client.checkin_part,
            (path, revision_id, metadata.ItemId, actor_id, references, preview),
            mutates=True,
        )
        if result.get("thumbnail_warning") or preview is None:
            warning(
                "ForgePDM",
                result.get("thumbnail_warning")
                or "CAD checked in successfully; its preview is unavailable.",
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
        result = yield Request(
            "Checking pending revision creation…",
            client.resume_revision_creation,
            (metadata.ItemId, revision_id),
            mutates=True,
            cancellable=False,
        )
        references = cad.capture(document)
        if result is not None:
            path = result.get("working_copy_path")
            if not path or not os.path.isfile(path) or os.path.islink(path):
                raise workspace.WorkspaceError(
                    "Revision recovered, but its local copy is missing; retrieve the revision or restore the copy"
                )
        else:
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
                (metadata.ItemId, note, revision_id, path),
                mutates=True,
                cancellable=False,
            )
        if os.path.realpath(path) == os.path.realpath(source_path):
            raise workspace.WorkspaceError(
                "The revision copy points to its source; both identities were preserved"
            )
        source = _guard_document(name, revision_id)
        if cad.document_modified(source) or source.FileName != source_path:
            raise workspace.WorkspaceError(
                "Source revision changed; the new revision copy was preserved"
            )
        # Existing assembly links retain the source document and its old identity.
        if any(
            d.FileName == path and cad.document_modified(d)
            for d in FreeCAD.listDocuments().values()
        ):
            raise workspace.WorkspaceError(
                "The recovered revision is already open with edits; its copy was preserved"
            )
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
    number_series = ("A",)
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
    number_series = ("A",)
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
    icon_name = "update-components"
    menu_text = "Update Selected Components from Server…"
    tooltip = "Review and adopt the latest uploaded snapshot of selected component occurrences"


class ManageComponentCommand(ReplaceRevisionCommand):
    icon_name = "manage-component"
    menu_text = "Manage Component…"
    tooltip = "Update a snapshot, adopt a newer revision, or replace a component"

    def action(self):
        choices = {
            "Update saved local changes of the same revision": UpdateSavedComponentsCommand,
            "Update snapshot of the same revision": UpdateSelectedComponentsCommand,
            "Adopt a newer revision of the same item": ReplaceRevisionCommand,
            "Replace with a different item": ReplaceComponentCommand,
        }
        choice = ask_choice("Manage Component", "Operation", list(choices))
        if choice is not None:
            yield from choices[choice]().action()


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


class DrawingBOMCommand(Command):
    icon_name = "drawing-bom"
    menu_text = "Drawing BOM…"
    tooltip = "Insert or update a direct, indented or flattened engineering BOM on a TechDraw page"
    needs_document = True
    number_series = ("A",)

    def action(self):
        from datetime import datetime, timezone
        from . import drawing_bom
        from .drawing_bom_ui import DrawingBOMDialog

        client = Session.require_client()
        actor = (Session.user or {}).get("id")
        document = _require_document()
        metadata = _require_metadata(document)
        name, revision_id, path = document.Name, metadata.RevisionId, document.FileName
        workspace.binding(path, client.base_url, require_uploaded=False)
        if workspace.working_path(path, client.base_url) is None:
            raise workspace.WorkspaceError(
                "Use Check Out / Renew to prepare a writable working copy before editing the drawing"
            )
        yield from _editable(client, metadata)
        lease = yield Request("Checking drawing checkout…", client.get_checkout, (revision_id,))
        if not lease or lease["user_id"] != actor:
            raise workspace.WorkspaceError(
                "Check out this Working assembly before changing the drawing"
            )
        report = yield Request("Loading drawing BOM report…", client.bom_report, (revision_id,))
        if not report["views"]["direct"]:
            raise workspace.WorkspaceError(
                "The stored BOM is empty. Review and synchronize it with BOM / Mass first"
            )
        document = _guard_document(name, revision_id)
        if FreeCADGui.getDocument(document.Name).getInEdit():
            raise workspace.WorkspaceError(
                "Finish the active CAD edit before changing a drawing BOM"
            )
        pages = [
            obj
            for obj in document.Objects
            if obj.isDerivedFrom("TechDraw::DrawPage") and obj.Template
        ]
        if not pages:
            raise workspace.WorkspaceError("Create a TechDraw page with a template first")
        selected = FreeCADGui.Selection.getSelection()
        preferred = next(
            (obj for obj in selected if obj.Document is document and hasattr(obj, "PDMTableData")),
            None,
        )
        dialog = DrawingBOMDialog(_main_window(), report, pages, preferred)
        if not execute_dialog(dialog):
            return
        page, target = dialog.page.currentData(), dialog.target.currentData()
        definition, notes = dialog.definition(), dialog.notes
        report = dialog.report
        x, y = dialog.x.value(), dialog.y.value()
        before = (
            (
                target.Symbol,
                target.PDMTableData,
                float(target.X),
                float(target.Y),
                float(target.Scale),
                float(target.Rotation),
            )
            if target
            else None
        )
        fresh = yield Request(
            "Revalidating drawing BOM evidence…", client.bom_report, (revision_id,)
        )
        yield Request("Checking edit permission…", client.bom_snapshot, (revision_id,))
        current = yield Request("Revalidating checkout…", client.get_checkout, (revision_id,))
        document = _guard_document(name, revision_id)
        if (
            Session.client is not client
            or (Session.user or {}).get("id") != actor
            or document.FileName != path
        ):
            raise workspace.WorkspaceError("Document or session changed; reopen Drawing BOM")
        if fresh["token"] != report["token"]:
            raise workspace.WorkspaceError(
                "Published BOM data changed; reopen Drawing BOM and review the new values"
            )
        if (
            not current
            or current["user_id"] != actor
            or (current["id"], current["version"]) != (lease["id"], lease["version"])
            or datetime.fromisoformat(current["expires_at"]) <= datetime.now(timezone.utc)
        ):
            raise workspace.WorkspaceError("Checkout changed or expired; reopen Drawing BOM")
        if document.getObject(page.Name) is not page or page not in pages:
            raise workspace.WorkspaceError("Drawing page changed")
        if target and (
            document.getObject(target.Name) is not target
            or before
            != (
                target.Symbol,
                target.PDMTableData,
                float(target.X),
                float(target.Y),
                float(target.Scale),
                float(target.Rotation),
            )
        ):
            raise workspace.WorkspaceError("Drawing table changed while checking the server")
        drawing_bom.apply(document, page, target, report, definition, notes, x, y)
        from . import drawing_balloons

        problems = drawing_balloons.issues(page)
        if problems:
            warning(
                "Drawing BOM",
                "Use Link BOM Balloon to reconcile these links before PDF publication:\n"
                + "\n".join(problems),
            )
        _open_status("Drawing BOM updated. Save and upload the drawing when ready.")


class CheckBOMBalloonLinksCommand(Command):
    icon_name = "check-bom-balloons"
    menu_text = "Check BOM Balloons…"
    tooltip = "Highlight broken BOM balloon links on the drawing and review their problems"
    needs_document = True

    def IsActive(self):
        document = FreeCAD.ActiveDocument
        return bool(
            not Session.busy
            and document is not None
            and any(obj.isDerivedFrom("TechDraw::DrawPage") for obj in document.Objects)
        )

    def action(self):
        from .balloon_review_ui import show_review

        document = _require_document()
        view = FreeCADGui.activeDocument().activeView()
        preferred = view.getPage() if hasattr(view, "getPage") else None
        show_review(_main_window(), document, preferred)
        yield from ()


class LinkBOMBalloonCommand(Command):
    icon_name = "link-bom-balloon"
    menu_text = "Link BOM Balloon…"
    tooltip = "Link or reconcile a native TechDraw balloon with a frozen Direct BOM Position"
    needs_document = True
    number_series = ("A",)

    def action(self):
        from datetime import datetime, timezone
        from . import drawing_balloons
        from .drawing_balloons_ui import LinkBalloonDialog

        from . import balloon_auto

        selected = FreeCADGui.Selection.getSelection()
        if len(selected) == 1 and selected[0].isDerivedFrom("TechDraw::DrawViewBalloon"):
            mode = ask_choice(
                "Link BOM Balloon",
                "Resolve from the connected geometry or choose an entry manually?",
                ["Automatic from arrow", "Manual entry"],
            )
            if mode is None:
                return
            if mode == "Automatic from arrow":
                yield from balloon_auto.workflow(selected[0])
                return

        client = Session.require_client()
        actor = (Session.user or {}).get("id")
        document = _require_document()
        metadata = _require_metadata(document)
        name, revision_id, path = document.Name, metadata.RevisionId, document.FileName
        workspace.binding(path, client.base_url, require_uploaded=False)
        if workspace.working_path(path, client.base_url) is None:
            raise workspace.WorkspaceError(
                "Use Check Out / Renew to prepare a writable working copy"
            )
        yield from _editable(client, metadata)
        lease = yield Request("Checking drawing checkout…", client.get_checkout, (revision_id,))
        if not lease or lease["user_id"] != actor:
            raise workspace.WorkspaceError(
                "Check out this Working assembly before linking balloons"
            )
        document = _guard_document(name, revision_id)
        if FreeCADGui.getDocument(name).getInEdit():
            raise workspace.WorkspaceError("Finish the active CAD edit before linking balloons")
        pages = [
            obj
            for obj in document.Objects
            if obj.isDerivedFrom("TechDraw::DrawPage") and obj.Template
        ]
        if not pages:
            raise workspace.WorkspaceError(
                "Create a TechDraw page, BOM table and native balloon first"
            )
        preferred = next(
            (
                obj
                for obj in FreeCADGui.Selection.getSelection()
                if obj.Document is document and obj.isDerivedFrom("TechDraw::DrawViewBalloon")
            ),
            None,
        )
        dialog = LinkBalloonDialog(_main_window(), pages, preferred)
        if not execute_dialog(dialog):
            return
        page, table, balloon = (
            dialog.page.currentData(),
            dialog.table.currentData(),
            dialog.balloon.currentData(),
        )
        key = dialog.row_key()
        from . import drawing_bom

        if drawing_bom.read_table(table)["report"].get("revision_id") != revision_id:
            raise workspace.WorkspaceError(
                "Update this table from the current assembly revision before linking balloons"
            )
        before = (
            table.PDMTableData,
            drawing_balloons.review_state(balloon),
        )
        yield from _editable(client, metadata)
        yield Request("Checking drawing edit permission…", client.bom_snapshot, (revision_id,))
        current = yield Request("Revalidating checkout…", client.get_checkout, (revision_id,))
        document = _guard_document(name, revision_id)
        if (
            Session.client is not client
            or (Session.user or {}).get("id") != actor
            or document.FileName != path
            or FreeCADGui.getDocument(name).getInEdit()
            or workspace.working_path(path, client.base_url) is None
        ):
            raise workspace.WorkspaceError("Document or session changed; reopen Link BOM Balloon")
        if (
            not current
            or current["user_id"] != actor
            or (current["id"], current["version"]) != (lease["id"], lease["version"])
            or datetime.fromisoformat(current["expires_at"]) <= datetime.now(timezone.utc)
        ):
            raise workspace.WorkspaceError("Checkout changed or expired; reopen Link BOM Balloon")
        if any(document.getObject(obj.Name) is not obj for obj in (page, table, balloon)):
            raise workspace.WorkspaceError("Drawing objects changed; reopen Link BOM Balloon")
        if before != (
            table.PDMTableData,
            drawing_balloons.review_state(balloon),
        ):
            raise workspace.WorkspaceError("Drawing link changed while checking the server")
        drawing_balloons.bind(document, page, balloon, table, key)
        _open_status("BOM balloon linked. Save and upload the drawing when ready.")


class ShowBOMCommand(Command):
    number_series = ("A",)
    icon_name = "bom"
    menu_text = "BOM / Mass…"
    tooltip = "Display the nested BOM or review and synchronize CAD occurrences"
    needs_document = True

    def action(self):
        from .bom_ui import BOMDialog

        client = Session.require_client()
        document = _require_document()
        metadata = _require_metadata(document)
        revision_id, name = metadata.RevisionId, document.Name

        def load():
            report = yield Request(
                "Loading published BOM report…", client.bom_report, (revision_id,)
            )
            if Session.client is not client:
                raise RuntimeError("Session changed; reopen BOM / Mass")
            _guard_document(name, revision_id)
            return report

        def prepare():
            current = _guard_document(name, revision_id)
            if cad.document_modified(current):
                raise RuntimeError("Save/upload the assembly before updating its BOM")
            references, path = cad.capture_bom(current), current.FileName
            prepared = yield Request(
                "Verifying uploaded CAD occurrences…",
                client.prepare_cad_bom,
                (path, revision_id, references),
            )
            snapshot = yield Request(
                "Loading editable BOM snapshot…", client.bom_snapshot, (revision_id,)
            )
            return dict(path=path, references=references, prepared=prepared, snapshot=snapshot)

        def apply(plan, proposal):
            current = _guard_document(name, revision_id)
            if (
                cad.document_modified(current)
                or current.FileName != plan["path"]
                or cad.capture_bom(current) != plan["references"]
            ):
                raise RuntimeError("CAD occurrences changed during review. Update from CAD again.")
            yield Request(
                "Applying BOM changes…",
                client.synchronize_cad_bom,
                (
                    plan["path"],
                    revision_id,
                    plan["references"],
                    plan["prepared"]["source_hash"],
                    [line.as_payload() for line in proposal],
                    plan["snapshot"],
                ),
                mutates=True,
                cancellable=False,
            )

        dialog = BOMDialog(_main_window(), metadata.ItemNumber, client, load, prepare, apply)
        execute_dialog(dialog)
        # Keep the command a workflow without blocking any HTTP calls on the GUI thread.
        yield from ()


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
    icon_name = "update-document"
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


class ConfigureWorkspaceCommand(Command):
    icon_name = "workspace"
    menu_text = "Set Workspace…"
    tooltip = "Set the local workspace once for this server and account"

    def action(self):
        root = _choose_workspace(Session.require_client(), force=True)
        if root:
            _open_status("Workspace configured: " + root)
        yield from ()


class DownloadCommand(Command):
    icon_name = "download"
    menu_text = "Open from ForgePDM…"
    tooltip = "Search items and retrieve a selected revision"

    def action(self):
        from .browser_panel import show_browser
        from .tasks import run

        client = Session.require_client()
        actor = (Session.user or {}).get("id")
        show_browser(
            _main_window(),
            client,
            actor,
            _configured_workspace(client),
            lambda: _choose_workspace(client, force=True),
            lambda selection: run(_browser_managed_operation(client, selection)),
            lambda selection: run(_insert_selected_configuration(client, selection)),
        )
        yield from ()


def _insert_selected_configuration(client, selection):
    from . import insertion

    document = _require_document()
    metadata = _require_metadata(document)
    name, rid, path = document.Name, metadata.RevisionId, document.FileName
    actor = (Session.user or {}).get("id")
    parent = insertion.assembly(document)
    if not selection["item"]["number"].startswith(("P", "A")):
        raise workspace.WorkspaceError("Insert a part or assembly item")
    if not metadata.ItemNumber.startswith("A"):
        raise workspace.WorkspaceError("Select a managed assembly as the insertion destination")
    if selection.get("actor_id") != actor or Session.client is not client:
        raise workspace.WorkspaceError("The browser session changed")
    yield from _editable(client, metadata)
    lease = yield from _authorize_tree_labels(client, document)
    baseline = tuple(o.Name for o in document.Objects)
    configuration, opened, complete = None, None, False
    try:
        configuration = yield Request(
            "Retrieving exact component snapshot…",
            client.retrieve_configuration,
            (
                selection["workspace"],
                selection["revision"]["id"],
                selection["dataset"]["id"],
                selection["file"]["id"],
            ),
        )
        opened = cad.open_configuration(configuration, _set_metadata)
        source = opened["root"]
        part = None
        if selection["item"]["number"].startswith("P"):
            targets = insertion.part_targets(source)
            if not targets:
                raise workspace.WorkspaceError("This part has no supported root geometry")
            choice = (
                targets[0].Name
                if len(targets) == 1
                else ask_choice(
                    "Insert Component",
                    "Choose the part object",
                    [o.Name for o in targets],
                    targets[0].Name,
                )
            )
            if choice is None:
                return
            part = source.getObject(choice)
        insertion.check_cycle(document, source)
        yield Request(
            "Recording verified component snapshot…", client.finish_configuration, (configuration,)
        )
        yield from _editable(client, metadata)
        current = yield from _authorize_tree_labels(client, document)
        if (
            Session.client is not client
            or (Session.user or {}).get("id") != actor
            or _guard_document(name, rid) is not document
            or document.FileName != path
            or tuple(o.Name for o in document.Objects) != baseline
            or parent is not insertion.assembly(document)
            or (lease["id"], lease["version"]) != (current["id"], current["version"])
        ):
            raise workspace.WorkspaceError("The destination or checkout changed; retry insertion")
        FreeCAD.setActiveDocument(name)
        link = insertion.insert(
            document,
            source,
            selection["item"]["number"] + "-" + selection["revision"]["label"],
            part,
        )
        complete = True
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(link)
        _record_recent(client, selection)
        _open_status(
            "Component inserted. Position it or add joints, then save/upload and review the BOM separately."
        )
    finally:
        if not complete:
            if opened is not None:
                cad.close_owned(opened["owned"])
            if configuration is not None:
                workspace.incomplete(configuration)
        if name in FreeCAD.listDocuments():
            FreeCAD.setActiveDocument(name)


def _open_selected_configuration(client, selection):
    actor = selection.get("actor_id")

    def guard_session():
        if actor and (Session.client is not client or (Session.user or {}).get("id") != actor):
            raise workspace.WorkspaceError("The session changed; open the browser again")

    guard_session()
    revision, dataset, file_record, root = (
        selection["revision"],
        selection["dataset"],
        selection["file"],
        selection["workspace"],
    )
    from .open_model import validate_workspace

    root = validate_workspace(root, client.base_url)
    from . import settings

    if (Session.user or {}).get("id"):
        settings.save_workspace(root, client.base_url, Session.user["id"])
    # Reuse only the exact recorded snapshot, never a different file of the same revision.
    for document in FreeCAD.listDocuments().values():
        if not document.FileName:
            continue
        metadata = document.getObject(METADATA_OBJECT)
        if metadata is None or getattr(metadata, "RevisionId", "") != revision["id"]:
            continue
        try:
            bound = workspace.binding(document.FileName, client.base_url, require_uploaded=False)
        except workspace.WorkspaceError:
            continue
        entry = bound["entry"]
        if entry.get("dataset_id") == dataset["id"] and entry.get("file_id") == file_record["id"]:
            # Recheck current access even when no transfer is required.
            yield Request(
                "Checking access to the open snapshot…", client.get_revision, (revision["id"],)
            )
            guard_session()
            current = FreeCAD.getDocument(document.Name)
            if current is not document or current.FileName != str(
                bound["directory"] / entry["path"]
            ):
                raise workspace.WorkspaceError(
                    "The open document changed while checking access; try again"
                )
            current_metadata = current.getObject(METADATA_OBJECT)
            if current_metadata is None or current_metadata.RevisionId != revision["id"]:
                raise workspace.WorkspaceError(
                    "The open revision changed while checking access; try again"
                )
            current_binding = workspace.binding(
                current.FileName, client.base_url, require_uploaded=False
            )
            if any(
                current_binding["entry"].get(key) != expected
                for key, expected in (("dataset_id", dataset["id"]), ("file_id", file_record["id"]))
            ):
                raise workspace.WorkspaceError(
                    "The open snapshot changed while checking access; try again"
                )
            FreeCAD.setActiveDocument(document.Name)
            _record_recent(client, selection)
            _open_status("Already open — local edits preserved.")
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
        guard_session()
        opened = cad.open_configuration(configuration, _set_metadata)
        yield Request(
            "Recording verified workspace configuration…",
            client.finish_configuration,
            (configuration,),
        )
        complete = True
        _record_recent(client, selection)
        _open_status(
            "Opened {} revision {} with its recorded components.".format(
                selection["item"]["number"], revision["label"]
            )
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


def _record_recent(client, selection):
    actor = selection.get("actor_id")
    if actor and Session.client is client and (Session.user or {}).get("id") == actor:
        from .browser_library import BrowserLibrary

        try:
            BrowserLibrary(client.base_url, actor).add_recent(selection)
        except (ValueError, RuntimeError, OSError) as error:
            FreeCAD.Console.PrintWarning(
                "ForgePDM: opened successfully, but Recent Items could not be saved: {}\n".format(
                    error
                )
            )


def _open_status(message):
    window = _main_window()
    if window is not None:
        window.statusBar().showMessage("ForgePDM: " + message, 8000)


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
    if not getattr(metadata, "ItemNumber", "").startswith(("P", "A", "S")):
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
    number_series = ("P", "A", "S")
    icon_name = "assign-material"
    menu_text = "Assign Material / Set Description…"
    tooltip = "Select an M material for a part or enter an assembly description"
    needs_document = True

    def GetResources(self):
        resources = super().GetResources()
        document = FreeCAD.ActiveDocument
        metadata = _metadata(document) if document else None
        series = getattr(metadata, "ItemNumber", "")[:1]
        if series in ("P", "A", "S"):
            resources["MenuText"] = translate(
                "ForgePDM", "Assign Material…" if series == "P" else "Set Description…"
            )
        return resources

    def action(self):
        from . import descriptions, tree_status

        client = Session.require_client()
        document = _require_document()
        metadata = _require_metadata(document)
        yield from _editable(client, metadata)
        yield from _authorize_tree_labels(client, document)
        name, revision_id = document.Name, metadata.RevisionId
        series = metadata.ItemNumber[:1]
        if series not in ("P", "A", "S"):
            raise ValueError("Select a managed P, A or S item")
        current = yield Request("Reading description…", client.get_description, (revision_id,))
        description, material_id = current["description"], current["material_revision_id"]
        physical = None
        if series in ("A", "S"):
            if series == "S" and current.get("origin") == "structured":
                information("ForgePDM", "Description is fixed by the purchasing specification.")
                return
            if series == "S" and "origin" not in current:
                raise ValueError("Update the backend to edit purchased descriptions")
            description = ask_text(
                "Assembly description" if series == "A" else "Purchasing description",
                "Description",
                description,
            )
            if description is None:
                return
            material_id = None
        else:
            choice = ask_choice(
                "Part material",
                "Action",
                ["Select material", "Clear material", "Enter component description", "Cancel"],
                "Select material",
            )
            if not choice or choice == "Cancel":
                return
            if choice == "Enter component description":
                capability = yield Request(
                    "Checking description support…", client.standard_capabilities
                )
                if capability.get("description_model_version", 0) < 2:
                    raise ValueError("Update the backend to use manual component descriptions")
                if material_id:
                    raise ValueError(
                        "Clear the material assignment before entering a manual description"
                    )
                description = ask_text("Component description", "Description", description)
                if description is None:
                    return
            elif choice == "Clear material":
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
    icon_name = "register-material"
    menu_text = "Register Raw Material…"
    tooltip = "Register an M description linked to a FreeCAD physical material"

    def action(self):
        from . import physical_materials

        client = Session.require_client()
        if not _source_language(client):
            return
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
    icon_name = "link-material"
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
                (item["id"], "Link physical material", revision["id"]),
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


class UpdateSavedComponentsCommand(Command):
    icon_name = "update-saved"
    menu_text = "Update Components from Saved Local Changes…"
    tooltip = "Review a saved local component generation without uploading it first"
    needs_document = True
    number_series = ("A",)

    def action(self):
        from . import insertion, managed_session, replacement

        client = Session.require_client()
        document = _require_document()
        metadata = _require_metadata(document)
        yield from _editable(client, metadata)
        yield from _authorize_tree_labels(client, document)
        _save_document(document)
        baseline = cad.capture_bom(document)
        selected = {o.Name for o in FreeCADGui.Selection.getSelection() if o.Document is document}
        groups = {}
        for ref in baseline:
            if ref.get("property_name", "LinkedObject") == "LinkedObject":
                groups.setdefault((ref["target_item_id"], ref["target_revision_id"]), []).append(
                    ref
                )
        choices = [
            rows
            for rows in groups.values()
            if not selected or any(r["object_name"] in selected for r in rows)
        ]
        if not choices:
            raise workspace.WorkspaceError("Select a direct managed component occurrence")
        if len(choices) > 1:
            labels = [rows[0]["component_label"] for rows in choices]
            choice = ask_choice("Update Components", "Choose a component", labels)
            if choice is None:
                return
            matching = choices[labels.index(choice)]
        else:
            matching = choices[0]
        rows = [
            dict(ref, occurrence_label=document.getObject(ref["object_name"]).Label)
            for ref in matching
        ]
        names = select_replacement_occurrences(rows, {ref["object_name"] for ref in matching})
        if not names:
            return
        if set(names) - {ref["object_name"] for ref in matching}:
            raise workspace.WorkspaceError(
                "Selected occurrences changed; review the component again"
            )
        source_revision = matching[0]["target_revision_id"]
        candidates = []
        for doc in FreeCAD.listDocuments().values():
            m = doc.getObject(METADATA_OBJECT)
            if (
                m is not None
                and m.RevisionId == source_revision
                and workspace.working_path(doc.FileName, client.base_url) is not None
                and not workspace.working_path(doc.FileName, client.base_url)["entry"].get(
                    "publication_staging"
                )
            ):
                candidates.append(doc)
        if not candidates:
            raise workspace.WorkspaceError(
                "Open the component for editing and save it locally first, or use Update from Server"
            )
        if len(candidates) > 1:
            labels = [doc.FileName for doc in candidates]
            choice = ask_choice("Update Components", "Choose the saved working copy", labels)
            if choice is None:
                return
            source = candidates[labels.index(choice)]
        else:
            source = candidates[0]
        if cad.document_modified(source):
            raise workspace.WorkspaceError("Save the component locally before adopting its changes")
        yield from _editable(client, _require_metadata(source))
        yield from _authorize_tree_labels(client, source)
        if not insertion.member_ids_current(source):
            _save_document(source)
        graph = cad.capture_graph(source)
        source_path = os.path.abspath(source.FileName)
        stamp = workspace.digest(source_path)[0]
        labels = [document.getObject(name).Label for name in names]
        if (
            ask_choice(
                "Update Components",
                "Adopt saved local changes for: " + ", ".join(labels),
                ["Apply", "Cancel"],
            )
            != "Apply"
        ):
            return
        configuration = yield Request(
            "Freezing saved local dependency graph…",
            managed_session.freeze,
            (client.base_url, graph, source_path),
        )
        opened = cad.open_configuration(configuration, _set_metadata)
        applied = False
        try:
            yield Request(
                "Recording immutable local generation…",
                client.finish_configuration,
                (configuration,),
            )
            yield from _authorize_tree_labels(client, document)
            if (
                cad.document_modified(source)
                or workspace.digest(source_path)[0] != stamp
                or cad.capture_bom(document) != baseline
            ):
                raise workspace.WorkspaceError("Source or assembly changed during review; retry")
            target = opened["root"]
            revision = dict(id=source_revision, item_id=matching[0]["target_item_id"])
            replacement.apply(
                document,
                baseline,
                names,
                target,
                revision,
                target_generation=configuration["ledger"]["root_file_id"],
            )
            applied = True
            FreeCAD.setActiveDocument(document.Name)
            information(
                "ForgePDM",
                "Saved local component changes adopted. Save the assembly and use Upload Assembly Graph to publish dependencies.",
            )
        finally:
            if not applied:
                cad.close_owned(opened["owned"])


class ReconcileRepresentationCommand(Command):
    icon_name = "reconcile-component"
    menu_text = "Reconcile Component Representation…"
    tooltip = "Review missing representation members against a verified saved source"
    needs_document = True
    number_series = ("A",)

    def action(self):
        from . import insertion, replacement

        client = Session.require_client()
        document = _require_document()
        yield from _editable(client, _require_metadata(document))
        yield from _authorize_tree_labels(client, document)
        groups = []
        for obj in document.Objects:
            group = insertion.representation(obj)
            if group is not None and group not in groups:
                groups.append(group)
        if not groups:
            raise workspace.WorkspaceError("No managed component representations found")
        before = replacement._joint_references(document)
        plans = []
        frozen_sources = {}
        for group in groups:
            import json

            evidence = json.loads(getattr(group, insertion.MARKER))
            if (
                evidence.get("version") not in (1, 2)
                or [o.Name for o in group.Group] != evidence["members"]
            ):
                raise workspace.WorkspaceError(
                    "Representation metadata is damaged; preserve it for manual recovery"
                )
            target = group.Group[0].LinkedObject
            if target is None or target.TypeId != "Assembly::AssemblyObject":
                raise workspace.WorkspaceError(
                    "Source Assembly identity is missing; recover its recorded snapshot first"
                )
            source = target.Document
            source_metadata = _require_metadata(source)
            expected_identity = [source_metadata.ItemId, source_metadata.RevisionId]
            if evidence.get("version") == 2:
                if [
                    evidence["source"]["item_id"],
                    evidence["source"]["revision_id"],
                ] != expected_identity:
                    raise workspace.WorkspaceError(
                        "Recorded source identity differs; restore the verified source before reconciliation"
                    )
            else:
                owners = [o for o in document.Objects if getattr(o, "LinkedObject", None) is group]
                if not owners or any(
                    json.loads(getattr(o, "ForgePDMOccurrenceKey", "[]"))[-2:] != expected_identity
                    for o in owners
                ):
                    raise workspace.WorkspaceError(
                        "Legacy occurrence identity is missing or inconsistent; recover its verified saved configuration"
                    )
            # This recovery is bounded to a verified uploaded source, including working copies.
            verified = yield Request(
                "Verifying saved source snapshot…",
                client.validate_references,
                (
                    [
                        dict(
                            target_path=source.FileName,
                            target_item_id=_require_metadata(source).ItemId,
                            target_revision_id=_require_metadata(source).RevisionId,
                            target_object_name=target.Name,
                            object_name=group.Name,
                            property_name="LinkedObject",
                        )
                    ],
                ),
            )
            pin = verified[0]
            key = (pin["target_revision_id"], pin["target_dataset_id"], pin["target_file_id"])
            if key not in frozen_sources:
                root = str(workspace.binding(document.FileName, client.base_url, False)["root"])
                configuration = yield Request(
                    "Retrieving the verified recovery snapshot…",
                    client.retrieve_configuration,
                    (root, *key),
                )
                opened = cad.open_configuration(configuration, _set_metadata)
                yield Request(
                    "Recording immutable recovery source…",
                    client.finish_configuration,
                    (configuration,),
                )
                frozen_sources[key] = opened["root"]
            frozen = frozen_sources[key]
            plans.append(
                (
                    group,
                    frozen,
                    workspace.digest(frozen.FileName)[0],
                    getattr(group, insertion.MARKER),
                )
            )
        if (
            ask_choice(
                "Reconcile Representation",
                "Rebuild {} representations from their verified sources, preserving occurrences and joints?".format(
                    len(plans)
                ),
                ["Reconcile", "Cancel"],
            )
            != "Reconcile"
        ):
            return
        yield from _authorize_tree_labels(client, document)
        document.openTransaction("Reconcile component representations")
        try:
            for group, source, source_hash, evidence_text in plans:
                if (
                    cad.document_modified(source)
                    or workspace.digest(source.FileName)[0] != source_hash
                    or getattr(group, insertion.MARKER) != evidence_text
                ):
                    raise workspace.WorkspaceError(
                        "Source or representation changed during review; reconciliation was not retained"
                    )
                insertion.retarget(group, source)
            document.recompute()
            if replacement._joint_references(document) != before:
                raise workspace.WorkspaceError(
                    "Joint references changed; reconciliation was rolled back"
                )
            replacement._check_errors(document)
            cad.capture_bom(document)
            document.commitTransaction()
        except BaseException:
            document.abortTransaction()
            document.recompute()
            raise
        information(
            "ForgePDM",
            "Representations reconciled. Inspect geometry and joints before saving/uploading.",
        )


class CancelCheckoutCommand(Command):
    icon_name = "cancel-checkout"
    menu_text = "Cancel Check Out…"
    tooltip = "Preserve recovery copies, abandon unpublished edits and release your checkout"
    needs_document = True

    def action(self):
        from . import checkout_cancel, insertion, managed_session, replacement

        client = Session.require_client()
        document = _require_document()
        control = getattr(FreeCADGui, "Control", None)
        if control is not None and control.activeDialog():
            raise workspace.WorkspaceError(
                "Finish the active CAD operation before cancelling checkout"
            )
        metadata = _require_metadata(document)
        actor = (Session.user or {}).get("id")
        name, revision_id = document.Name, metadata.RevisionId
        path = document.FileName
        revision = yield Request(
            "Checking cancellation identity…", client.get_revision, (revision_id,)
        )
        if revision["item_id"] != metadata.ItemId:
            raise workspace.WorkspaceError(
                "The working document identity differs from the server revision"
            )
        working = workspace.working_path(path, client.base_url)
        if working is not None and working["entry"].get("publication_staging"):
            raise workspace.WorkspaceError(
                "Select the original editable working copy for cancellation"
            )
        if working is None:
            raise workspace.WorkspaceError(
                "Select the editable working copy before cancelling its checkout"
            )
        intent = yield Request(
            "Reviewing checkout cancellation…",
            checkout_cancel.prepare,
            (client, path, metadata.RevisionId, (Session.user or {}).get("id")),
        )
        affected = []
        for parent in FreeCAD.listDocuments().values():
            if parent is document:
                continue
            related = False
            for candidate in parent.Objects:
                if candidate.TypeId not in ("App::Link", "Assembly::AssemblyLink"):
                    continue
                pointed = candidate.LinkedObject
                if pointed is None or isinstance(pointed, tuple) or pointed.Document is parent:
                    continue
                if pointed.Document is document:
                    related = True
                    break
                try:
                    if managed_session.unpublished_origin(
                        pointed.Document.FileName, client.base_url, path
                    ):
                        related = True
                        break
                except workspace.WorkspaceError:
                    continue
            if not related:
                continue
            names = []
            internal = insertion.internal_names(parent, validate=False)
            for obj in parent.Objects:
                if obj.Name in internal or obj.TypeId not in (
                    "App::Link",
                    "Assembly::AssemblyLink",
                ):
                    continue
                target = (
                    insertion.identity_source(obj)
                    if insertion.representation(obj) is not None
                    else obj.LinkedObject
                )
                if target is None or target.Document is parent:
                    continue
                target_doc = target.Document
                if target_doc is document or managed_session.unpublished_origin(
                    target_doc.FileName, client.base_url, path
                ):
                    names.append(obj.Name)
            if names:
                yield from _editable(client, _require_metadata(parent))
                yield from _authorize_tree_labels(client, parent)
                affected.append((parent, names))
        summary = "Abandon unpublished edits to {} and restore {} affected parent assembly(s)? Uploaded history is retained. Recovery: {}".format(
            document.Label, len(affected), intent["recovery"]
        )
        if (
            ask_choice("Cancel Check Out", summary, ["Cancel Check Out", "Keep editing"])
            != "Cancel Check Out"
        ):
            return
        if not intent["payload"]["file_id"] and affected:
            raise workspace.WorkspaceError(
                "This revision has no published snapshot. Resolve dependent parents before cancellation"
            )
        originals = [document] + [parent for parent, names in affected]
        for original in originals:
            from uuid import uuid4

            original.saveCopy(
                str(Path(intent["recovery"]) / (original.Name + "-" + uuid4().hex + ".FCStd"))
            )
        target = None
        if intent["payload"]["file_id"]:
            root = str(workspace.binding(path, client.base_url, False)["root"])
            config = yield Request(
                "Retrieving cancellation restoration snapshot…",
                client.retrieve_configuration,
                (
                    root,
                    metadata.RevisionId,
                    intent["payload"]["dataset_id"],
                    intent["payload"]["file_id"],
                ),
            )
            opened = cad.open_configuration(config, _set_metadata)
            target = opened["root"]
            yield Request(
                "Recording restoration configuration…", client.finish_configuration, (config,)
            )
        restoration_plans = []
        for parent, names in affected:
            yield from _authorize_tree_labels(client, parent)
            if parent.HasPendingTransaction:
                raise workspace.WorkspaceError(
                    "Finish the current parent CAD operation before cancellation"
                )
            restoration_plans.append(
                (parent, names, cad.capture_bom(parent, allow_incomplete=True))
            )
        begun = []
        try:
            for parent, names, refs in restoration_plans:
                parent.openTransaction("Restore cancelled component")
                begun.append(parent)
                replacement.apply(
                    parent,
                    refs,
                    names,
                    target,
                    dict(id=metadata.RevisionId, item_id=metadata.ItemId),
                    restoration=True,
                    within_transaction=True,
                )
            for parent in begun:
                parent.commitTransaction()
        except BaseException:
            for parent in reversed(begun):
                parent.abortTransaction()
                parent.recompute()
            raise
        intent = yield Request(
            "Recording prepared restoration…",
            checkout_cancel.record,
            (client, path, intent, "restored"),
        )
        yield Request(
            "Cancelling the exact reviewed checkout…",
            checkout_cancel.release,
            (client, intent),
            mutates=True,
            cancellable=False,
        )
        current_checkout = yield Request(
            "Checking cancellation completion…",
            client.get_checkout,
            (revision_id,),
            cancellable=False,
        )
        if current_checkout is not None:
            yield Request(
                "Recording original cancellation completion…",
                checkout_cancel.record,
                (client, path, intent, "complete"),
                cancellable=False,
            )
            information(
                "ForgePDM",
                "The original checkout was cancelled. A newer checkout exists; its working document and edits were retained.",
            )
            return
        tree_observer.revoke_revision(metadata.RevisionId)
        intent = yield Request(
            "Recording cancellation result…",
            checkout_cancel.record,
            (client, path, intent, "released"),
            cancellable=False,
        )
        _guard_managed_session(client, actor)
        document = _guard_document(name, revision_id)
        # Retain edits made while the server operation was in flight, too.
        from uuid import uuid4

        document.saveCopy(str(Path(intent["recovery"]) / ("final-" + uuid4().hex + ".FCStd")))
        for other in FreeCAD.listDocuments().values():
            if other is document:
                continue
            if any(
                getattr(getattr(obj, "LinkedObject", None), "Document", None) is document
                for obj in other.Objects
            ):
                raise workspace.WorkspaceError(
                    "Checkout cancelled; new dependent links keep the original document open. Recover cancellation after reviewing them."
                )
        FreeCAD.closeDocument(document.Name)
        if target is not None:
            FreeCAD.setActiveDocument(target.Name)
        yield Request(
            "Completing local cancellation…",
            checkout_cancel.record,
            (client, path, intent, "complete"),
            cancellable=False,
        )
        information(
            "ForgePDM",
            "Checkout cancelled. Uploaded snapshots remain intact. Recovery copies: "
            + intent["recovery"],
        )


class UploadAssemblyGraphCommand(Command):
    icon_name = "upload-graph"
    menu_text = "Upload Assembly Graph…"
    tooltip = "Publish the selected assembly and saved dependencies in child-first order"
    needs_document = True
    checkin = False

    def action(self):
        from . import managed_session

        client = Session.require_client()
        document = _require_document()
        yield from _editable(client, _require_metadata(document))
        yield from _authorize_tree_labels(client, document)
        if (
            ask_choice(
                "Save and Publish Assembly Graph",
                "Save the selected assembly locally and review its dependency graph?",
                ["Continue", "Cancel"],
            )
            != "Continue"
        ):
            return
        import json

        root_path = os.path.abspath(document.FileName)
        graph_journal = (
            workspace.binding(root_path, client.base_url, False)["directory"]
            / "graph-publication.json"
        )
        recovering = (
            graph_journal.exists()
            and json.loads(graph_journal.read_text()).get("state") != "complete"
        )
        nodes = {}
        if not recovering:
            for dependency in cad.dependency_documents(document):
                if cad.document_modified(dependency) or dependency is document:
                    yield from _editable(client, _require_metadata(dependency))
                    yield from _authorize_tree_labels(client, dependency)
                    _save_document(dependency)
            nodes = cad.capture_graph(document)
            subtree_publication = yield Request(
                "Checking saved dependency states…",
                managed_session.publication_requirements,
                (client, nodes, root_path),
            )
            for saved_path in managed_session.publication_order(nodes, root_path):
                node = nodes[saved_path]
                if not subtree_publication[saved_path]:
                    continue
                lease = yield Request(
                    "Checking dependency checkout…",
                    client.get_checkout,
                    (node["identity"]["revision_id"],),
                )
                if not lease:
                    if (
                        ask_choice(
                            "Dependency Checkout",
                            "Acquire checkout for "
                            + node["identity"]["item_number"]
                            + " to publish its saved changes?",
                            ["Acquire checkout", "Cancel"],
                        )
                        != "Acquire checkout"
                    ):
                        return
                    yield Request(
                        "Acquiring dependency checkout…",
                        client.acquire_checkout,
                        (node["identity"]["revision_id"],),
                        mutates=True,
                        cancellable=False,
                    )
        plan = yield Request(
            "Preparing dependency publication review…",
            managed_session.prepare_publication,
            (client, nodes, root_path, (Session.user or {}).get("id"), self.checkin),
        )
        labels = [
            plan["nodes"][path]["identity"]["item_number"]
            for path in plan["order"]
            if plan["steps"][path]["needs_publication"]
        ]
        if (
            ask_choice(
                "Check In Assembly Graph" if self.checkin else "Upload Assembly Graph",
                "Publish in this order: " + ", ".join(labels),
                ["Publish", "Cancel"],
            )
            != "Publish"
        ):
            return
        for path in plan["order"]:
            step = plan["steps"][path]
            if step["state"] == "complete":
                continue
            if step.get("alias_of"):
                yield Request(
                    "Reusing the verified shared dependency…",
                    managed_session.complete_alias,
                    (client, plan, path),
                )
                continue
            if step["state"] == "published":
                yield from _open_published_graph_step(client, plan, path)
                continue
            if not step["needs_publication"]:
                step.update(published_path=path, state="complete")
                continue
            staged = yield Request(
                "Preparing exact saved document…",
                managed_session.stage_publication,
                (client, plan, path),
            )
            existing = next(
                (d for d in FreeCAD.listDocuments().values() if d.FileName == staged), None
            )
            doc = existing or FreeCAD.openDocument(staged)
            if existing is not None and cad.document_modified(doc):
                raise workspace.WorkspaceError(
                    "Staged publication copy has unsaved edits; preserve and inspect it before recovery"
                )
            yield from _authorize_tree_labels(client, doc, allow_staging=True)
            _save_document(doc)
            refs = cad.capture(doc)
            expected_targets = {
                r["object_name"]: plan["steps"][r["target_path"]]["published_path"]
                for r in plan["nodes"][path]["references"]
            }
            if any(
                os.path.abspath(ref["target_path"])
                != os.path.abspath(expected_targets.get(ref["object_name"], ""))
                for ref in refs
            ):
                raise workspace.WorkspaceError(
                    "Native references differ from the reviewed publication graph"
                )
            preview = thumbnail_render.optional(doc)
            yield Request(
                "Publishing " + plan["nodes"][path]["identity"]["item_number"] + "…",
                managed_session.publish_step,
                (client, plan, path, refs, preview),
                mutates=True,
                cancellable=False,
            )
            tree_observer.revoke_document(doc)
            if self.checkin:
                tree_observer.revoke_revision(plan["nodes"][path]["identity"]["revision_id"])
            yield from _open_published_graph_step(client, plan, path)
        yield Request(
            "Recording completed assembly publication…", managed_session.acknowledge_graph, (plan,)
        )
        FreeCAD.setActiveDocument(document.Name)
        information(
            "ForgePDM",
            "Assembly graph published. Original editing documents and local generations were retained. Review engineering BOM synchronization separately.",
        )


class CheckInAssemblyGraphCommand(UploadAssemblyGraphCommand):
    icon_name = "checkin-graph"
    menu_text = "Check In Assembly Graph…"
    checkin = True


class OpenForEditingCommand(CheckoutCommand):
    icon_name = "open-editing"
    menu_text = "Open for Editing…"
    tooltip = "Prepare a separate working copy and review available same-revision component updates"

    def action(self):
        yield from super().action()
        document = _require_document()
        client = Session.require_client()
        if workspace.working_path(document.FileName, client.base_url) is None:
            return
        _save_document(document)
        if not _require_metadata(document).ItemNumber.startswith("A"):
            return
        refs = cad.capture_bom(document)
        revisions = list(dict.fromkeys(r["target_revision_id"] for r in refs))
        if not revisions:
            return
        response = yield Request(
            "Checking component updates…", client.revision_status, (revisions,)
        )
        available = []
        for status in response["items"]:
            latest = status.get("latest_snapshot")
            if not latest:
                continue
            matching = [r for r in refs if r["target_revision_id"] == status["revision_id"]]
            if not matching:
                continue
            entry = workspace.binding(matching[0]["target_path"], client.base_url, False)["entry"]
            if (entry.get("dataset_id"), entry.get("file_id")) != (
                latest["dataset_id"],
                latest["file_id"],
            ):
                available.append((status, matching))
        if (
            not available
            or ask_choice(
                "Component Updates",
                "Newer uploads are available for: "
                + ", ".join(s["item_number"] for s, rows in available),
                ["Review updates", "Keep saved configuration"],
            )
            != "Review updates"
        ):
            return
        for status, matching in available:
            FreeCAD.setActiveDocument(document.Name)
            FreeCADGui.Selection.clearSelection()
            for ref in matching:
                FreeCADGui.Selection.addSelection(document.getObject(ref["object_name"]))
            yield from UpdateSelectedComponentsCommand().action()
            _save_document(document)


def _browser_managed_operation(client, selection):
    if selection.get("intent") == "cancel_checkout":
        import json

        revision_id = selection["revision"]["id"]
        candidates = [
            d
            for d in FreeCAD.listDocuments().values()
            if d.getObject(METADATA_OBJECT) is not None
            and _metadata(d).RevisionId == revision_id
            and workspace.working_path(d.FileName, client.base_url) is not None
            and not workspace.working_path(d.FileName, client.base_url)["entry"].get(
                "publication_staging"
            )
        ]
        if not candidates:
            paths = []
            for ledger_path in (Path(selection["workspace"]) / "working").glob(
                "*/" + workspace.MANIFEST
            ):
                if ledger_path.is_symlink():
                    continue
                ledger = json.loads(ledger_path.read_text())
                if ledger.get("server_url") != client.base_url:
                    continue
                for entry in ledger["documents"]:
                    if entry.get("publication_staging"):
                        continue
                    candidate_path = workspace._safe_path(ledger_path.parent, entry["path"])
                    candidate_revision = entry.get("revision_id")
                    if not candidate_revision:
                        from . import fcstd

                        try:
                            tree, _ = fcstd.inspect(candidate_path)
                            node = tree.find(
                                "./ObjectData/Object[@name='ForgePDM_Metadata']/Properties/Property[@name='RevisionId']/String"
                            )
                            candidate_revision = node.get("value") if node is not None else None
                        except (OSError, ValueError, fcstd.CADIntegrityError):
                            continue
                    if candidate_revision == revision_id:
                        paths.append(str(candidate_path))
            if not paths:
                raise workspace.WorkspaceError(
                    "No managed working copy was found. Open the existing working copy before cancellation."
                )
            chosen = (
                paths[0]
                if len(paths) == 1
                else ask_choice(
                    "Cancel Check Out", "Choose the working copy to preserve and cancel", paths
                )
            )
            if chosen is None:
                return
            candidates = [FreeCAD.openDocument(chosen)]
        selected = candidates[0] if len(candidates) == 1 else None
        if selected is None:
            paths = [d.FileName for d in candidates]
            chosen = ask_choice("Cancel Check Out", "Choose the working copy", paths)
            if chosen is None:
                return
            selected = candidates[paths.index(chosen)]
        FreeCAD.setActiveDocument(selected.Name)
        yield from CancelCheckoutCommand().action()
        return
    yield from _open_selected_configuration(client, selection)
    if selection.get("intent") == "edit":
        yield from OpenForEditingCommand().action()


def _open_published_graph_step(client, plan, path):
    from . import managed_session

    dataset = plan["steps"][path]["result"]["dataset"]
    root = str(workspace.binding(plan["root"], client.base_url, False)["root"])
    config = yield Request(
        "Opening the exact published dependency…",
        client.retrieve_configuration,
        (
            root,
            plan["nodes"][path]["identity"]["revision_id"],
            dataset["id"],
            dataset["files"][0]["id"],
        ),
    )
    opened = cad.open_configuration(config, _set_metadata)
    yield Request("Recording published dependency…", client.finish_configuration, (config,))
    yield Request(
        "Recording graph dependency result…",
        managed_session.record_published_configuration,
        (client, plan, path, opened["root"].FileName),
    )


def _guard_managed_session(client, actor):
    if Session.client is not client or (Session.user or {}).get("id") != actor:
        raise workspace.WorkspaceError(
            "The session changed; recover the original operation after signing in again"
        )
