"""GUI-thread FreeCAD adapter for whole-object external App::Link references."""

import os
from pathlib import Path

from .workspace import WorkspaceError, _safe_path


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


def open_configuration(configuration, set_metadata):
    import FreeCAD as App

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
            document.save()
        verify(configuration, documents)
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
            if document.isTouched():
                retained.append(document.Name)
            else:
                App.closeDocument(document.Name)
        except (NameError, ReferenceError):
            continue
    return retained
