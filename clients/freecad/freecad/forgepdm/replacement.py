"""GUI-thread, explicit whole-object revision replacement with local rollback."""

from . import tree_labels
from .workspace import WorkspaceError

LINK_TYPES = ("App::Link", "Assembly::AssemblyLink")


def _joint_references(document):
    result = []
    for obj in document.Objects:
        proxy = type(getattr(obj, "Proxy", None))
        if proxy.__module__ != "JointObject" or proxy.__name__ not in ("Joint", "GroundedJoint"):
            continue
        for name in obj.PropertiesList:
            kind = obj.getTypeIdOfProperty(name)
            if "Link" not in kind:
                continue
            value = getattr(obj, name)
            if value is None:
                continue
            if "LinkSub" in kind:
                if not isinstance(value, tuple) or len(value) != 2:
                    raise WorkspaceError(
                        "Unsupported joint reference: {}.{}".format(obj.Name, name)
                    )
                target, subnames = value
                if target is None:
                    raise WorkspaceError("Unresolved joint reference: {}.{}".format(obj.Name, name))
                for path in subnames:
                    if "?" in path or (path and target.getSubObject(path) is None):
                        raise WorkspaceError(
                            "Unresolved joint geometry: {}.{}".format(obj.Name, name)
                        )
                result.append((obj.Name, name, target.Document.Name, target.Name, tuple(subnames)))
            else:
                if not hasattr(value, "Document"):
                    raise WorkspaceError(
                        "Unsupported joint reference: {}.{}".format(obj.Name, name)
                    )
                result.append((obj.Name, name, value.Document.Name, value.Name))
    return result


def _check_errors(document):
    for obj in document.Objects:
        if any(state in ("Invalid", "Error") for state in getattr(obj, "State", [])):
            raise WorkspaceError(
                "CAD object '{}' has an error; replacement was not retained".format(obj.Name)
            )


def apply(document, references, selected_names, target_document, revision):
    """Replace only reviewed direct occurrences. Never save, upload or edit a BOM."""
    metadata = target_document.getObject("ForgePDM_Metadata")
    parent_metadata = document.getObject("ForgePDM_Metadata")
    if (
        metadata is None
        or metadata.RevisionId != revision["id"]
        or metadata.ItemId != revision["item_id"]
        or metadata.ServerUrl != parent_metadata.ServerUrl
    ):
        raise WorkspaceError("Replacement document does not match the chosen item/revision/server")
    selected = list(selected_names)
    if not selected or len(selected) != len(set(selected)):
        raise WorkspaceError("Choose distinct component occurrences to replace")
    by_name = {ref["object_name"]: ref for ref in references}
    plan = []
    for name in selected:
        ref = by_name.get(name)
        if ref is None or ref["target_item_id"] != revision["item_id"]:
            raise WorkspaceError("Replacement must use a newer revision of the same component item")
        if ref["target_revision_id"] == revision["id"]:
            raise WorkspaceError("The selected occurrence already uses that revision")
        obj = document.getObject(name)
        target = target_document.getObject(ref["target_object_name"])
        if obj is None or obj.TypeId not in LINK_TYPES or getattr(obj, "ElementCount", 0):
            raise WorkspaceError("Only direct whole-object component occurrences can be replaced")
        if target is None or target.TypeId in LINK_TYPES:
            raise WorkspaceError(
                "The new revision has no compatible target object '{}'; map it manually".format(
                    ref["target_object_name"]
                )
            )
        original = obj.LinkedObject
        if original is None or isinstance(original, tuple):
            raise WorkspaceError("The source occurrence is unresolved")
        if obj.TypeId == "Assembly::AssemblyLink" and target.TypeId != "Assembly::AssemblyObject":
            raise WorkspaceError("A native subassembly requires an Assembly target")
        if original.Document is not document and original.TypeId != target.TypeId:
            raise WorkspaceError("Replacement target object type differs from the original")
        plan.append((name, target, obj.Placement))
    if document.HasPendingTransaction:
        raise WorkspaceError("Finish the current FreeCAD operation before replacing a revision")
    occurrences_before = {
        name: (document.getObject(name).LinkedObject, document.getObject(name).Placement)
        for name in by_name
    }
    before = _joint_references(document)
    source_documents = set()
    for name, target, placement in plan:
        current = document.getObject(name).LinkedObject
        visited = set()
        while current.Document is document and current.TypeId in LINK_TYPES:
            if current.Name in visited:
                raise WorkspaceError("Internal component link cycle")
            visited.add(current.Name)
            current = current.LinkedObject
        source_documents.add(current.Document.Name)
    if any(reference[2] in source_documents for reference in before):
        raise WorkspaceError(
            "Joint references must use assembly occurrences, not external source objects"
        )
    _check_errors(document)
    document.openTransaction("Replace component revision")
    try:
        for name, target, placement in plan:
            obj = document.getObject(name)
            if obj.TypeId == "Assembly::AssemblyLink":
                obj.LinkedObject = target
            else:
                obj.setLink(target)
            obj.Placement = placement
        document.recompute()
        if _joint_references(document) != before:
            raise WorkspaceError("Joint references changed; replacement was rolled back")
        _check_errors(document)
        tree_labels.refresh(document, within_transaction=True)
        document.recompute()
        for name, target, placement in plan:
            obj = document.getObject(name)
            if obj.LinkedObject is not target or obj.Placement != placement:
                raise WorkspaceError("Replacement changed a target or placement unexpectedly")
        expected_targets = {name: target for name, target, placement in plan}
        for name, (original, placement) in occurrences_before.items():
            obj = document.getObject(name)
            if (
                obj.LinkedObject is not expected_targets.get(name, original)
                or obj.Placement != placement
            ):
                raise WorkspaceError(
                    "Replacement altered an unselected occurrence or component placement"
                )
        _check_errors(document)
        document.commitTransaction()
    except BaseException:
        document.abortTransaction()
        document.recompute()
        raise
    return len(plan)
