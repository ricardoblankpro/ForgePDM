"""GUI-thread FreeCAD adapter for whole-object external App::Link references."""

import os
from pathlib import Path

from . import fasteners, tree_labels
from .workspace import WorkspaceError, _safe_path


def document_modified(document):
    """Recompute clears touched flags; GUI Modified tracks unsaved edits as well."""
    import FreeCADGui

    return document.isTouched() or FreeCADGui.getDocument(document.Name).Modified


def settle_techdraw(document, timeout=30):
    """Let queued native HLR/face results settle before saving an owned snapshot."""
    if not any(
        getattr(obj, "TypeId", "").startswith("TechDraw::")
        for obj in getattr(document, "Objects", ())
    ):
        return
    from time import monotonic

    import FreeCAD as App

    from .ui import QtCore

    name = document.Name
    loop, timer = QtCore.QEventLoop(), QtCore.QTimer()
    deadline, quiet, failure = monotonic() + timeout, [0], []

    def poll():
        try:
            current = App.getDocument(name)
        except NameError:
            current = None
        if current is not document:
            failure.append("The document was closed while waiting for TechDraw")
        elif monotonic() >= deadline:
            failure.append("TechDraw is still computing. Let drawing updates finish and retry.")
        else:
            quiet[0] = (
                quiet[0] + 1 if QtCore.QThreadPool.globalInstance().activeThreadCount() == 0 else 0
            )
        if failure or quiet[0] >= 3:
            loop.quit()

    timer.timeout.connect(poll)
    timer.start(20)
    execute = getattr(loop, "exec", None) or loop.exec_
    execute()
    timer.stop()
    if failure:
        raise WorkspaceError(failure[0])


def rebase_links(document):
    """Refresh FreeCAD's cached relative paths after changing FileName."""
    for name in [obj.Name for obj in document.Objects]:
        obj = document.getObject(name)
        if obj is None or obj.TypeId not in ("App::Link", "Assembly::AssemblyLink"):
            continue
        target = obj.LinkedObject
        if target is None or isinstance(target, tuple) or target.Document is document:
            continue
        placement = obj.Placement
        if obj.TypeId == "Assembly::AssemblyLink":
            # Native AssemblyLink has no usable Python setLink binding. Clearing
            # the XLink property also invalidates its cached relative file path.
            obj.LinkedObject = None
            obj.LinkedObject = target
        else:
            obj.setLink(None)
            obj.setLink(target)
        obj.Placement = placement
    for obj in fasteners.objects(document):
        attached = fasteners.attachment(obj)
        if attached and attached[0].Document is not document:
            target, subelement = attached
            obj.BaseObject = None
            obj.BaseObject = (target, [subelement])
    document.recompute()


def capture(document):
    references = []
    for obj in document.Objects:
        if obj.TypeId not in ("App::Link", "Assembly::AssemblyLink"):
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
    for obj in fasteners.objects(document):
        attached = fasteners.attachment(obj)
        if not attached:
            continue
        target, subelement = attached
        if target.Document is document:
            continue
        target_document = target.Document
        metadata = target_document.getObject("ForgePDM_Metadata")
        if (
            metadata is None
            or not getattr(metadata, "ItemId", "")
            or not getattr(metadata, "RevisionId", "")
        ):
            raise WorkspaceError(
                "Upload the fastener attachment target as a managed component first"
            )
        if document_modified(target_document):
            raise WorkspaceError("Fastener attachment target has unsaved changes")
        references.append(
            dict(
                object_name=obj.Name,
                property_name="BaseObject",
                target_path=os.path.abspath(target_document.FileName),
                target_object_name=target.Name,
                target_item_id=metadata.ItemId,
                target_revision_id=metadata.RevisionId,
                target_subelement=subelement,
            )
        )
    return references


def _subassembly_generated_members(document, link):
    """Exclude native projected children; the linked assembly owns their BOM."""
    target = link.LinkedObject
    if (
        target is None
        or isinstance(target, tuple)
        or target.Document is document
        or target.TypeId != "Assembly::AssemblyObject"
        or getattr(link, "ElementCount", 0)
    ):
        raise WorkspaceError("Native subassembly must link a whole external Assembly object")
    generated, pending = set(), list(link.Group)
    while pending:
        child = pending.pop()
        if child.Document is not document or child.Name in generated:
            continue
        if child.Name == link.Name:
            raise WorkspaceError("Native subassembly contains a generated member cycle")
        generated.add(child.Name)
        pending.extend(getattr(child, "Group", []))
    return generated


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
    ignored.update(obj.Name for obj in members if obj.TypeId.startswith("TechDraw::"))
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
    components = {
        obj.Name for obj in members if obj.TypeId in ("App::Link", "Assembly::AssemblyLink")
    }
    generated = set()
    for member in members:
        if member.TypeId == "Assembly::AssemblyLink":
            generated.update(_subassembly_generated_members(document, member))
    if generated & (components | ignored):
        raise WorkspaceError("Generated subassembly members overlap direct assembly members")
    ignored.update(generated)
    for member in members:
        if (
            member.Name not in ignored
            and not fasteners.recognized(member)
            and member.TypeId
            not in (
                "App::Link",
                "Assembly::AssemblyLink",
            )
        ):
            raise WorkspaceError(
                "Unsupported Assembly member '{}' ({}). "
                "This BOM adapter counts direct whole-object component links.".format(
                    member.Name, member.TypeId
                )
            )
    return ignored, components


def validate_fastener_membership(document, obj):
    """A toolbar-created root fastener belongs to the sole assembly's direct BOM."""
    for parent in document.Objects:
        if obj in getattr(parent, "Group", ()) and parent.TypeId != "Assembly::AssemblyObject":
            raise WorkspaceError("Fasteners in nested local groups require a dedicated BOM adapter")


def capture_bom(document):
    """Capture candidate direct occurrences; internal links resolve to external pins.

    Plain groups/parts organize occurrences in this document. Linked external
    assemblies are single components; their documents are never flattened.
    Selection of engineering components happens in the review dialog.
    """
    ignored, assembly_components = _builtin_bom_context(document)
    result = []
    for obj in document.Objects:
        if (
            obj.Name == "ForgePDM_Metadata"
            or obj.Name in ignored
            or obj.TypeId.startswith("TechDraw::")
        ):
            continue
        if fasteners.recognized(obj):
            validate_fastener_membership(document, obj)
            continue
        if getattr(obj, "Proxy", None) is not None:
            raise WorkspaceError(
                "Unsupported BOM proxy on '{}' ({}). A dedicated adapter is required.".format(
                    obj.Name, type(obj.Proxy).__name__
                )
            )
        if (obj.TypeId.startswith("Assembly::") and obj.TypeId != "Assembly::AssemblyLink") or (
            obj.TypeId.startswith("App::Link") and obj.TypeId != "App::Link"
        ):
            raise WorkspaceError(
                "Unsupported BOM object '{}' ({}). A dedicated adapter is required.".format(
                    obj.Name, obj.TypeId
                )
            )
        if obj.TypeId not in ("App::Link", "Assembly::AssemblyLink"):
            continue
        if assembly_components is not None and obj.Name not in assembly_components:
            raise WorkspaceError(
                "Component link '{}' is outside the built-in Assembly's direct members. "
                "Nested local groups require a dedicated BOM adapter.".format(obj.Name)
            )
        current, visited = obj, set()
        while current.Document is document and current.TypeId in (
            "App::Link",
            "Assembly::AssemblyLink",
        ):
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
        if current.TypeId in ("App::Link", "Assembly::AssemblyLink"):
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
    for entry in fasteners.capture(document):
        if entry["object_name"] not in ignored:
            result.append(
                dict(
                    object_name=entry["object_name"],
                    property_name="PDMStandardAssociation",
                    target_revision_id=entry["revision_id"],
                    occurrence_id=entry["occurrence_id"],
                    geometry=entry["geometry"],
                    component_label=entry["object_name"],
                )
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
                if reference["property_name"] == "BaseObject":
                    if (
                        link is None
                        or not fasteners.recognized(link)
                        or target is None
                        or not fasteners.subelement_exists(target, reference["target_subelement"])
                    ):
                        raise WorkspaceError("Pinned fastener attachment cannot be reconstructed")
                    link.BaseObject = (target, [reference["target_subelement"]])
                    continue
                if (
                    link is None
                    or link.TypeId not in ("App::Link", "Assembly::AssemblyLink")
                    or target is None
                ):
                    raise WorkspaceError(
                        "A recorded CAD object is missing from its pinned native file"
                    )
                if link.LinkedObject is not target:
                    placement = link.Placement
                    if link.TypeId == "Assembly::AssemblyLink":
                        link.LinkedObject = target
                    else:
                        link.setLink(target)
                    link.Placement = placement
            document.recompute()
            settle_techdraw(document)
            if document.HasPendingTransaction:
                document.commitTransaction()
            presentation = tree_labels.refresh(document)
            if presentation["changed"]:
                # Legacy snapshots get new metadata properties during label
                # projection. Saving clears GUI Modified, but not feature Touched.
                document.recompute()
                settle_techdraw(document)
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
        expected_occurrences = entry.get("standard_occurrences", [])
        if expected_occurrences or fasteners.objects(document):
            actual_occurrences = fasteners.capture(document)
            if actual_occurrences != sorted(
                expected_occurrences, key=lambda row: row["object_name"]
            ):
                raise WorkspaceError(
                    "Retrieved standard associations differ from the uploaded evidence"
                )
        for reference in entry["references"]:
            obj = document.getObject(reference["object_name"])
            if reference["property_name"] == "BaseObject":
                attached = fasteners.attachment(obj) if obj is not None else None
                if not attached or attached[1] != reference["target_subelement"]:
                    raise WorkspaceError("Pinned fastener subelement did not resolve")
                target = attached[0]
            else:
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
