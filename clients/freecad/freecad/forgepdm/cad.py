"""GUI-thread FreeCAD adapter for whole-object external App::Link references."""

import os
from pathlib import Path

from .workspace import WorkspaceError, _safe_path
from . import tree_labels


def document_modified(document):
    """Recompute clears touched flags; GUI Modified tracks unsaved edits as well."""
    import FreeCADGui

    return document.isTouched() or FreeCADGui.getDocument(document.Name).Modified


def rebase_links(document):
    """Refresh FreeCAD's cached relative paths after changing FileName."""
    for obj in document.Objects:
        if obj.TypeId != "App::Link":
            continue
        target = obj.LinkedObject
        if target is None or isinstance(target, tuple) or target.Document is document:
            continue
        placement = obj.Placement
        obj.setLink(None)
        obj.setLink(target)
        obj.Placement = placement
    document.recompute()


def capture(document):
    references = []
    for obj in document.Objects:
        if obj.TypeId != "App::Link":
            continue
        target = obj.LinkedObject
        if target is None:
            continue  # The serialized archive check detects unresolved external links.
        if isinstance(target, tuple):
            raise WorkspaceError("Subelement links require a dedicated reference adapter")
        target_document = target.Document
        if target_document is document:
            continue
        if target_document.isTouched():
            raise WorkspaceError(
                "Linked component '{}' has unsaved changes. Save/upload it first.".format(
                    target_document.Label
                )
            )
        metadata = target_document.getObject("ForgePDM_Metadata")
        if (
            metadata is None
            or not getattr(metadata, "ItemId", "")
            or not getattr(metadata, "RevisionId", "")
        ):
            raise WorkspaceError(
                "Upload linked component '{}' to a managed workspace first.".format(
                    target_document.Label
                )
            )
        references.append(
            {
                "object_name": obj.Name,
                "property_name": "LinkedObject",
                "target_path": os.path.abspath(target_document.FileName),
                "target_object_name": target.Name,
                "target_item_id": metadata.ItemId,
                "target_revision_id": metadata.RevisionId,
            }
        )
    return references


def _builtin_bom_context(document):
    assemblies = [obj for obj in document.Objects if obj.TypeId == "Assembly::AssemblyObject"]
    if not assemblies:
        return set(), None
    if len(assemblies) != 1:
        raise WorkspaceError(
            "BOM extraction supports one built-in Assembly container per document. "
            "Use linked external subassemblies for nested product structure."
        )
    assembly = assemblies[0]
    if getattr(assembly, "Proxy", None) is not None:
        raise WorkspaceError(
            "Custom native Assembly container proxies require a dedicated BOM adapter"
        )
    ignored = {assembly.Name}
    members = list(assembly.Group)
    for group in members:
        if group.TypeId != "Assembly::JointGroup":
            continue
        if getattr(group, "Proxy", None) is not None:
            raise WorkspaceError(
                "Custom Assembly joint-group proxies require a dedicated BOM adapter"
            )
        ignored.add(group.Name)
        for joint in group.Group:
            proxy_type = type(getattr(joint, "Proxy", None))
            if (
                joint.TypeId != "App::FeaturePython"
                or proxy_type.__module__ != "JointObject"
                or proxy_type.__name__ not in ("Joint", "GroundedJoint")
            ):
                raise WorkspaceError(
                    "Unsupported built-in Assembly joint '{}': {}.{}".format(
                        joint.Name, proxy_type.__module__, proxy_type.__name__
                    )
                )
            ignored.add(joint.Name)
    for member in members:
        if member.Name not in ignored and member.TypeId != "App::Link":
            raise WorkspaceError(
                "Unsupported Assembly member '{}' ({}). "
                "This BOM adapter counts direct whole-object component links.".format(
                    member.Name, member.TypeId
                )
            )
    return ignored, {obj.Name for obj in members if obj.TypeId == "App::Link"}


def capture_bom(document):
    """Capture candidate direct occurrences; internal links resolve to external pins.

    Plain groups/parts organize occurrences in this document. Linked external
    assemblies are single components; their documents are never flattened.
    Selection of engineering components happens in the review dialog.
    """
    ignored, assembly_components = _builtin_bom_context(document)
    result = []
    for obj in document.Objects:
        if obj.Name == "ForgePDM_Metadata" or obj.Name in ignored:
            continue
        if getattr(obj, "Proxy", None) is not None:
            raise WorkspaceError(
                "Unsupported BOM proxy on '{}' ({}). A dedicated adapter is required.".format(
                    obj.Name, type(obj.Proxy).__name__
                )
            )
        if obj.TypeId.startswith("Assembly::") or (
            obj.TypeId.startswith("App::Link") and obj.TypeId != "App::Link"
        ):
            raise WorkspaceError(
                "Unsupported BOM object '{}' ({}). A dedicated adapter is required.".format(
                    obj.Name, obj.TypeId
                )
            )
        if obj.TypeId != "App::Link":
            continue
        if assembly_components is not None and obj.Name not in assembly_components:
            raise WorkspaceError(
                "Component link '{}' is outside the built-in Assembly's direct members. "
                "Nested local groups require a dedicated BOM adapter.".format(obj.Name)
            )
        current, visited = obj, set()
        while current.Document is document and current.TypeId == "App::Link":
            if current.Name in visited:
                raise WorkspaceError("Internal CAD link cycle")
            visited.add(current.Name)
            if getattr(current, "ElementCount", 0):
                raise WorkspaceError("Link arrays/subelements require a dedicated BOM adapter")
            target = current.LinkedObject
            if target is None or isinstance(target, tuple):
                raise WorkspaceError("Unresolved/subelement CAD link cannot enter a BOM")
            current = target
        if current.Document is document:
            raise WorkspaceError(
                "Internal links to local geometry have no pinned component identity"
            )
        if current.TypeId == "App::Link":
            raise WorkspaceError("External link-to-link targets require a dedicated BOM adapter")
        target_document = current.Document
        metadata = target_document.getObject("ForgePDM_Metadata")
        if metadata is None:
            raise WorkspaceError(
                "Linked component '{}' has no ForgePDM identity. Upload it before synchronizing the BOM.".format(
                    getattr(target_document, "Label", target_document.FileName)
                )
            )
        if document_modified(target_document):
            component = getattr(metadata, "ItemNumber", "") or target_document.FileName
            revision = getattr(metadata, "RevisionLabel", "")
            raise WorkspaceError(
                "Component {} Rev {} has unsaved changes in FreeCAD. "
                "Save it and upload changed content before synchronizing the BOM.".format(
                    component, revision
                )
            )
        result.append(
            {
                "object_name": obj.Name,
                "property_name": "LinkedObject",
                "target_path": os.path.abspath(target_document.FileName),
                "target_object_name": current.Name,
                "target_item_id": getattr(metadata, "ItemId", ""),
                "target_revision_id": getattr(metadata, "RevisionId", ""),
                "component_label": "{} / {} — {}".format(
                    getattr(metadata, "ItemNumber", ""),
                    getattr(metadata, "RevisionLabel", ""),
                    getattr(current, "Label", current.Name),
                ),
            }
        )
    return result


def open_configuration(configuration, set_metadata):
    import FreeCAD as App
    import FreeCADGui as Gui

    directory = Path(configuration["directory"])
    ledger = configuration["ledger"]
    entries = {entry["file_id"]: entry for entry in ledger["documents"]}
    paths = {key: _safe_path(directory, entry["path"]) for key, entry in entries.items()}
    existing = {
        Path(document.FileName).resolve()
        for document in App.listDocuments().values()
        if document.FileName
    }
    if any(path.resolve() in existing for path in paths.values()):
        raise WorkspaceError(
            "A document in this configuration is already open; it was not replaced"
        )
    owned = []
    try:
        documents = {}
        for key in ledger["order"]:
            document = App.openDocument(str(paths[key]))
            owned.append(document)
            documents[key] = document
            entry = entries[key]
            set_metadata(
                document,
                ItemId=entry["item_id"],
                RevisionId=entry["revision_id"],
                ItemNumber=entry["item_number"],
                RevisionLabel=entry["revision_label"],
                ServerUrl=ledger["server_url"],
            )
        for key in ledger["order"]:
            document = documents[key]
            for reference in entries[key]["references"]:
                link = document.getObject(reference["object_name"])
                target_document = documents[reference["target_file_id"]]
                target = target_document.getObject(reference["target_object_name"])
                if link is None or link.TypeId != "App::Link" or target is None:
                    raise WorkspaceError(
                        "A recorded CAD object is missing from its pinned native file"
                    )
                if link.LinkedObject is not target:
                    placement = link.Placement
                    link.setLink(target)
                    link.Placement = placement
            document.recompute()
            if document.HasPendingTransaction:
                document.commitTransaction()
            tree_labels.refresh(document)
            # App.Document.save() can leave Gui.Document.Modified set after our
            # metadata/relink edits. The GUI save clears it only on success.
            Gui.getDocument(document.Name).save()
            if document_modified(document):
                raise WorkspaceError(
                    "Retrieved component '{}' could not be saved cleanly; "
                    "the configuration was not completed.".format(document.Label)
                )
        verify(configuration, documents)
        if any(document_modified(document) for document in documents.values()):
            raise WorkspaceError(
                "A reconstructed component changed after saving; the configuration was not completed."
            )
        root = documents[ledger["root_file_id"]]
        App.setActiveDocument(root.Name)
        return {"root": root, "documents": documents, "owned": owned}
    except BaseException:
        close_owned(owned)
        raise


def verify(configuration, documents):
    for entry in configuration["ledger"]["documents"]:
        document = documents[entry["file_id"]]
        for reference in entry["references"]:
            obj = document.getObject(reference["object_name"])
            target = obj.LinkedObject if obj is not None else None
            expected = documents[reference["target_file_id"]]
            if (
                target is None
                or target.Name != reference["target_object_name"]
                or target.Document is not expected
            ):
                raise WorkspaceError(
                    "External CAD reference did not resolve to its pinned document/object"
                )


def close_owned(documents):
    import FreeCAD as App

    retained = []
    for document in reversed(documents):
        try:
            current = App.getDocument(document.Name)
            if current is not document:
                continue
            if document_modified(document):
                retained.append(document.Name)
            else:
                App.closeDocument(document.Name)
        except (NameError, ReferenceError):
            continue
    return retained
