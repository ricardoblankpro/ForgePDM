"""Persistent occurrence allocation and GUI-thread tree-label projection.

No FreeCAD imports: allocation can be tested without CAD. Document adaptation is
called only by the GUI thread, on editable documents or owned reconstruction.
"""

import json
from uuid import UUID, uuid4

from .workspace import WorkspaceError


FIELDS = {
    "ForgePDMOccurrenceId": "App::PropertyString",
    "ForgePDMOccurrenceNumber": "App::PropertyInteger",
    "ForgePDMOccurrenceKey": "App::PropertyString",
    "ForgePDMOriginalLabel": "App::PropertyString",
}
STATE = "TreeOccurrenceState"


def _uuid(value):
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        return None


def allocate(records, encoded_state, owner_item_id):
    """Plan all allocations before mutation. Records are in CAD creation order."""
    try:
        state = json.loads(encoded_state) if encoded_state else {}
        if not isinstance(state, dict):
            raise ValueError
        if state and (
            state["version"] != 1
            or not isinstance(state["owners"], dict)
            or not isinstance(state["counters"], dict)
        ):
            raise ValueError
        if state.get("owner_item_id") != owner_item_id:
            state = {"version": 1, "owner_item_id": owner_item_id, "owners": {}, "counters": {}}
        if any(type(value) is not int or value < 0 for value in state["counters"].values()):
            raise ValueError
        for identity, owner in state["owners"].items():
            if not _uuid(identity) or set(owner) != {"name", "key", "number"}:
                raise ValueError
            if (
                not isinstance(owner["name"], str)
                or not isinstance(owner["key"], str)
                or type(owner["number"]) is not int
                or owner["number"] <= 0
            ):
                raise ValueError
            state["counters"][owner["key"]] = max(
                state["counters"].get(owner["key"], 0), owner["number"]
            )
    except (ValueError, TypeError, KeyError) as error:
        raise WorkspaceError("Invalid tree occurrence registry; it was not overwritten") from error
    names = [record["name"] for record in records]
    if len(names) != len(set(names)):
        raise WorkspaceError("Duplicate CAD object names in occurrence allocation")
    planned, seen_ids, occupied = [], set(), set()
    for record in records:
        key = json.dumps(
            [record["scope"], record["item_id"], record["revision_id"]], separators=(",", ":")
        )
        identity = _uuid(record.get("identity", ""))
        owner = state["owners"].get(identity)
        if owner is None:
            identity = None
        # A copied link carries its source's properties. The registered original
        # keeps its identity even when the copy appears earlier in the object list.
        if identity in seen_ids or (owner and owner["name"] != record["name"]):
            identity = None
            owner = None
        number = None
        if identity and owner and owner["key"] == key:
            number = owner["number"]
        if number is not None:
            if (key, number) in occupied:
                raise WorkspaceError("Conflicting registered tree occurrence numbers")
            occupied.add((key, number))
            state["counters"][key] = max(state["counters"].get(key, 0), number)
        identity = identity or str(uuid4())
        seen_ids.add(identity)
        planned.append({**record, "identity": identity, "key": key, "number": number})
    for row in planned:
        if row["number"] is None:
            number = state["counters"].get(row["key"], 0) + 1
            state["counters"][row["key"]] = number
            row["number"] = number
        state["owners"][row["identity"]] = {
            "name": row["name"],
            "key": row["key"],
            "number": row["number"],
        }
        row["label"] = "{}-{}|{}".format(row["item_number"], row["revision_label"], row["number"])
    return planned, json.dumps(state, sort_keys=True, separators=(",", ":"))


def _scopes(document):
    containers = {"App::Part", "Assembly::AssemblyObject"}
    groups = containers | {"App::DocumentObjectGroup"}
    parents = {}
    for obj in document.Objects:
        if obj.TypeId in groups:
            for child in obj.Group:
                if child.Document is document:
                    parents.setdefault(child.Name, []).append(obj)

    def ancestors(name, path=()):
        if name in path:
            raise WorkspaceError("CAD container cycle prevents tree occurrence numbering")
        result = set()
        for parent in parents.get(name, []):
            result.add(parent.Name)
            result.update(ancestors(parent.Name, path + (name,)))
        return result

    def scope(obj):
        candidates = {
            name for name in ancestors(obj.Name) if document.getObject(name).TypeId in containers
        }
        closest = {
            name
            for name in candidates
            if not any(name in ancestors(other) for other in candidates if other != name)
        }
        if len(closest) > 1:
            raise WorkspaceError(
                "Component '{}' belongs to multiple assembly containers".format(obj.Name)
            )
        return next(iter(closest), "$document")

    return scope


def _projected_labels(document, metadata):
    """Generated AssemblyLink children display their pinned source occurrence.

    They belong to the external assembly's registry, not the local parent's.
    Labels are copied for presentation only; never parsed to recover identity.
    """
    projected = {}
    server = getattr(metadata, "ServerUrl", "")
    for assembly in document.Objects:
        if assembly.TypeId != "Assembly::AssemblyLink":
            continue
        source = getattr(assembly, "LinkedObject", None)
        if source is None or isinstance(source, tuple) or source.Document is document:
            continue
        source_metadata = source.Document.getObject("ForgePDM_Metadata")
        if not server or getattr(source_metadata, "ServerUrl", "") != server:
            continue
        for child in assembly.Group:
            if child.Document is not document or child.TypeId not in (
                "App::Link",
                "Assembly::AssemblyLink",
            ):
                continue
            target = child.LinkedObject
            if (
                target is None
                or isinstance(target, tuple)
                or target.Document is not source.Document
            ):
                raise WorkspaceError("Generated subassembly child has an unexpected source")
            if child.Name in projected and projected[child.Name] != target.Label:
                raise WorkspaceError("Ambiguous generated subassembly child label")
            projected[child.Name] = target.Label
    return projected


def _records(document, metadata, projected):
    scope = _scopes(document)
    records, skipped = [], []
    server = getattr(metadata, "ServerUrl", "")
    for obj in document.Objects:
        if obj.Name in projected or obj.TypeId not in ("App::Link", "Assembly::AssemblyLink"):
            continue
        current, visited = obj, set()
        while current.Document is document and current.TypeId in (
            "App::Link",
            "Assembly::AssemblyLink",
        ):
            if current.Name in visited:
                raise WorkspaceError("CAD link cycle prevents tree occurrence numbering")
            visited.add(current.Name)
            if getattr(current, "ElementCount", 0):
                current = None
                break
            current = current.LinkedObject
            if current is None or isinstance(current, tuple):
                current = None
                break
        target = (
            current.Document.getObject("ForgePDM_Metadata")
            if current is not None and current.Document is not document
            else None
        )
        if target is None or not all(
            getattr(target, field, "")
            for field in ("ItemId", "RevisionId", "ItemNumber", "RevisionLabel")
        ):
            skipped.append(obj.Name)
            continue
        target_server = getattr(target, "ServerUrl", "")
        if not server or target_server != server:
            skipped.append(obj.Name)
            continue
        records.append(
            {
                "name": obj.Name,
                "scope": scope(obj),
                "item_id": target.ItemId,
                "revision_id": target.RevisionId,
                "item_number": target.ItemNumber,
                "revision_label": target.RevisionLabel,
                "identity": getattr(obj, "ForgePDMOccurrenceId", ""),
            }
        )
    return records, skipped


def _property(obj, name, kind, value):
    if name in obj.PropertiesList:
        if obj.getTypeIdOfProperty(name) != kind:
            raise WorkspaceError("Incompatible ForgePDM property: {}.{}".format(obj.Name, name))
    else:
        obj.addProperty(kind, name, "ForgePDM")
    if getattr(obj, name) != value:
        setattr(obj, name, value)
    obj.setEditorMode(name, 1)


def refresh(document, within_transaction=False):
    """Apply presentation metadata to one authorized/owned document, atomically."""
    metadata = document.getObject("ForgePDM_Metadata")
    if metadata is None or not all(
        getattr(metadata, field, "")
        for field in ("ItemId", "RevisionId", "ItemNumber", "RevisionLabel")
    ):
        return {"changed": False, "labels": [], "skipped": []}
    projected = _projected_labels(document, metadata)
    records, skipped = _records(document, metadata, projected)
    planned, encoded = allocate(records, getattr(metadata, STATE, ""), metadata.ItemId)
    root_label = "{}-{}".format(metadata.ItemNumber, metadata.RevisionLabel)
    changed = document.Label != root_label or getattr(metadata, STATE, "") != encoded
    for row in planned:
        obj = document.getObject(row["name"])
        changed |= (
            obj.Label != row["label"]
            or getattr(obj, "ForgePDMOccurrenceId", "") != row["identity"]
            or getattr(obj, "ForgePDMOccurrenceNumber", 0) != row["number"]
            or getattr(obj, "ForgePDMOccurrenceKey", "") != row["key"]
        )
    changed |= any(document.getObject(name).Label != label for name, label in projected.items())
    if not changed:
        return {"changed": False, "labels": [row["label"] for row in planned], "skipped": skipped}
    # Validate property types before opening the transaction, preserving conflicts.
    for obj, fields in [
        (metadata, {STATE: "App::PropertyString", "TreeOriginalLabel": "App::PropertyString"})
    ] + [(document.getObject(row["name"]), FIELDS) for row in planned]:
        for name, kind in fields.items():
            if name in obj.PropertiesList and obj.getTypeIdOfProperty(name) != kind:
                raise WorkspaceError("Incompatible ForgePDM property: {}.{}".format(obj.Name, name))
    if getattr(document, "HasPendingTransaction", False) and not within_transaction:
        raise WorkspaceError("Finish the current FreeCAD operation before refreshing tree labels")
    if not within_transaction:
        document.openTransaction("Refresh ForgePDM tree labels")
    try:
        if not getattr(metadata, "TreeOriginalLabel", ""):
            _property(metadata, "TreeOriginalLabel", "App::PropertyString", document.Label)
        _property(metadata, STATE, "App::PropertyString", encoded)
        document.Label = root_label
        for row in planned:
            obj = document.getObject(row["name"])
            if not getattr(obj, "ForgePDMOriginalLabel", ""):
                _property(obj, "ForgePDMOriginalLabel", "App::PropertyString", obj.Label)
            _property(obj, "ForgePDMOccurrenceId", FIELDS["ForgePDMOccurrenceId"], row["identity"])
            _property(
                obj, "ForgePDMOccurrenceNumber", FIELDS["ForgePDMOccurrenceNumber"], row["number"]
            )
            _property(obj, "ForgePDMOccurrenceKey", FIELDS["ForgePDMOccurrenceKey"], row["key"])
            obj.Label = row["label"]
        for name, label in projected.items():
            document.getObject(name).Label = label
        if not within_transaction:
            document.commitTransaction()
    except BaseException:
        if not within_transaction:
            document.abortTransaction()
        raise
    return {"changed": True, "labels": [row["label"] for row in planned], "skipped": skipped}
