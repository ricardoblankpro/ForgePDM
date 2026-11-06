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


def target_objects(document):
    """Offer whole spatial objects, excluding features owned by their containers."""
    containers = {"PartDesign::Body", "App::Part", "Assembly::AssemblyObject"}
    contained = {
        child.Name
        for obj in document.Objects
        if obj.TypeId in containers
        for child in obj.Group
        if child.Document is document
    }
    candidates = []
    for obj in document.Objects:
        if obj.Name in contained or obj.TypeId in LINK_TYPES:
            continue
        if obj.TypeId in containers or (
            obj.isDerivedFrom("Part::Feature") and not obj.Shape.isNull()
        ):
            candidates.append(obj)
    return candidates


def apply(
    document,
    references,
    selected_names,
    target_document,
    revision,
    target_names=None,
    target_snapshot=None,
):
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
    by_name = {ref["object_name"]: ref for ref in references if ref.get("property_name", "LinkedObject") == "LinkedObject"}
    if target_snapshot is not None:
        if target_names is not None or not all(
            target_snapshot.get(key) for key in ("dataset_id", "file_id")
        ):
            raise WorkspaceError("Snapshot updates require exact pins and unchanged object mapping")
        if metadata.ItemId == parent_metadata.ItemId:
            raise WorkspaceError("An assembly cannot contain its own item")
    if target_names is not None:
        if set(target_names) != set(selected):
            raise WorkspaceError("Map every selected occurrence to a replacement object")
        if metadata.ItemId == parent_metadata.ItemId:
            raise WorkspaceError("An assembly cannot contain its own item")
        if (
            len(
                {
                    (by_name[n]["target_item_id"], by_name[n]["target_revision_id"])
                    for n in selected
                    if n in by_name
                }
            )
            != 1
        ):
            raise WorkspaceError("Replace occurrences of one source item/revision at a time")
        eligible = {obj.Name for obj in target_objects(target_document)}
        if any(name not in eligible for name in target_names.values()):
            raise WorkspaceError("Choose a whole replacement object, not an internal feature")
    plan = []
    for name in selected:
        ref = by_name.get(name)
        if ref is None or (target_names is None and ref["target_item_id"] != revision["item_id"]):
            raise WorkspaceError("Replacement must use a newer revision of the same component item")
        target_name = ref["target_object_name"] if target_names is None else target_names[name]
        if target_snapshot is not None:
            if ref["target_revision_id"] != revision["id"]:
                raise WorkspaceError("Snapshot update must keep the exact component revision")
            if not ref.get("target_dataset_id") or not ref.get("target_file_id"):
                raise WorkspaceError("Original component snapshot pins are required")
            if (ref["target_dataset_id"], ref["target_file_id"]) == (
                target_snapshot["dataset_id"],
                target_snapshot["file_id"],
            ):
                raise WorkspaceError("The selected occurrence already uses that snapshot")
        elif (
            ref["target_revision_id"] == revision["id"] and target_name == ref["target_object_name"]
        ):
            raise WorkspaceError("The selected occurrence already uses that revision and object")
        obj = document.getObject(name)
        target = target_document.getObject(target_name)
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
        if (
            target_names is None
            and original.Document is not document
            and original.TypeId != target.TypeId
        ):
            raise WorkspaceError("Replacement target object type differs from the original")
        plan.append((name, target, obj.Placement))
    for other_name in by_name.keys() - set(selected):
        current = document.getObject(other_name).LinkedObject
        visited = set()
        while current is not None and current.Document is document and current.TypeId in LINK_TYPES:
            if current.Name in selected:
                raise WorkspaceError(
                    "Unselected occurrence '{}' depends on a selected local link; select dependent occurrences too".format(
                        other_name
                    )
                )
            if current.Name in visited:
                raise WorkspaceError("Internal component link cycle")
            visited.add(current.Name)
            current = current.LinkedObject
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
    document.openTransaction("Replace component")
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
