"""Native rigid component representations; source documents are never edited."""

import json
from uuid import uuid4

from . import fasteners
from .workspace import WorkspaceError

MARKER = "ForgePDMRepresentation"


def assembly(document):
    rows = [o for o in document.Objects if o.TypeId == "Assembly::AssemblyObject"]
    if len(rows) != 1:
        raise WorkspaceError("Insertion requires exactly one native Assembly container")
    return rows[0]


def representation(obj):
    target = getattr(obj, "LinkedObject", None)
    return target if target is not None and hasattr(target, MARKER) else None


def source(obj):
    group = representation(obj)
    if group is None:
        return None
    try:
        data = json.loads(getattr(group, MARKER))
        if data["version"] not in (1, 2) or group.TypeId != "App::Part":
            raise ValueError()
        members = list(group.Group)
        if [o.Name for o in members] != data["members"] or not members:
            raise ValueError()
        target = members[0].LinkedObject
        if target is None or target.TypeId != "Assembly::AssemblyObject":
            raise ValueError()
        if data["version"] == 2:
            identity = target.Document.getObject("ForgePDM_Metadata")
            if (
                data["source"]["item_id"] != identity.ItemId
                or data["source"]["revision_id"] != identity.RevisionId
            ):
                raise ValueError()
            for link in members:
                original = link.LinkedObject
                record = data["targets"][link.Name]
                if original is None or record["name"] != original.Name:
                    raise ValueError()
                if record.get("identity") and record["identity"] != getattr(
                    original, "ForgePDMMemberId", None
                ):
                    raise ValueError()
        expected = source_members(target.Document)
        if len(expected) != len(members):
            raise ValueError()
        for link, original in zip(members, expected):
            if (
                link.TypeId != "App::Link"
                or link.LinkedObject is not original
                or getattr(link, "ElementCount", 0)
            ):
                raise ValueError()
            if hasattr(link, "Placement") and not link.Placement.isSame(original.Placement, 1e-9):
                raise ValueError()
        return target
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise WorkspaceError(
            "Component representation differs from its source. Use Reconcile Component Representation to review recovery; no links were changed"
        ) from error


def internal_names(document, validate=True):
    names = set()
    for obj in document.Objects:
        if representation(obj) is not None:
            source(obj) if validate else identity_source(obj)
            group = representation(obj)
            names.add(group.Name)
            names.update(o.Name for o in group.Group)
    return names


def source_members(document):
    root = assembly(document)
    contained, pending = set(), list(root.Group)
    while pending:
        obj = pending.pop()
        if obj.Document is not document or obj.Name in contained:
            continue
        contained.add(obj.Name)
        pending.extend(getattr(obj, "Group", ()))
    extras = [o for o in fasteners.objects(document) if o.Name not in contained]
    for obj in extras:
        if not fasteners.recognized(obj) or obj.Shape.isNull():
            raise WorkspaceError("Fasteners Workbench is required to insert this assembly")
    return [root] + sorted(extras, key=lambda o: o.Name)


def part_targets(document):
    from .replacement import target_objects

    # RootObjects also excludes bodies referenced by drawings, not only owned bodies.
    return [
        obj
        for obj in target_objects(document)
        if obj.TypeId != "Assembly::AssemblyObject"
        and not fasteners.recognized(obj)
        and hasattr(obj, "Shape")
        and not obj.Shape.isNull()
    ]


def check_cycle(destination, source_document):
    item_id = destination.getObject("ForgePDM_Metadata").ItemId
    seen, pending = set(), [source_document]
    while pending:
        doc = pending.pop()
        if doc.Name in seen:
            continue
        seen.add(doc.Name)
        metadata = doc.getObject("ForgePDM_Metadata")
        if metadata is not None and metadata.ItemId == item_id:
            raise WorkspaceError(
                "An assembly cannot contain itself, including through dependencies"
            )
        pending.extend(
            o.LinkedObject.Document
            for o in doc.Objects
            if o.TypeId in ("App::Link", "Assembly::AssemblyLink")
            and o.LinkedObject is not None
            and not isinstance(o.LinkedObject, tuple)
            and o.LinkedObject.Document is not doc
        )


def build(document, source_document, label):
    group = document.addObject("App::Part", "ForgePDMComponent")
    members = []
    for original in source_members(source_document):
        link = document.addObject("App::Link", "ComponentMember")
        link.setLink(original)
        link.Placement = original.Placement
        link.Visibility = original.Visibility
        group.addObject(link)
        members.append(link.Name)
    group.addProperty("App::PropertyString", MARKER, "ForgePDM")
    write_evidence(group, source_document)
    group.setEditorMode(MARKER, 1)
    group.Label = label + " representation"
    return group


def retarget(group, source_document):
    """Keep native member names so joint paths survive compatible replacements."""
    document = group.Document
    previous = {link.Name: link for link in group.Group}
    evidence = json.loads(getattr(group, MARKER))
    targets = evidence.get("targets", {})
    members = []
    for original in source_members(source_document):
        matches = [
            link
            for link in previous.values()
            if (
                (
                    getattr(link, "LinkedObject", None).Name
                    if getattr(link, "LinkedObject", None) is not None
                    else targets.get(link.Name, {}).get("name")
                )
                == original.Name
                and (
                    not getattr(original, "ForgePDMMemberId", "")
                    or not targets.get(link.Name, {}).get("identity")
                    or targets[link.Name]["identity"] == original.ForgePDMMemberId
                )
            )
        ]
        if len(matches) > 1:
            raise WorkspaceError("Ambiguous component member identity; explicit mapping required")
        link = previous.pop(matches[0].Name) if matches else None
        if link is None:
            link = document.addObject("App::Link", "ComponentMember")
        if link.LinkedObject is not original:
            link.setLink(original)
        if not link.Placement.isSame(original.Placement, 1e-9):
            link.Placement = original.Placement
        if link.Visibility != original.Visibility:
            link.Visibility = original.Visibility
        members.append(link)
    group.Group = members
    for link in previous.values():
        document.removeObject(link.Name)
    write_evidence(group, source_document)
    return group


def insert(document, source_document, label, part=None):
    parent = assembly(document)
    if getattr(document, "HasPendingTransaction", False):
        raise WorkspaceError("Finish the current FreeCAD operation before insertion")
    check_cycle(document, source_document)
    document.openTransaction("ForgePDM Insert Component")
    try:
        target = build(document, source_document, label) if part is None else part
        link = parent.newObject("App::Link", "Component")
        link.setLink(target)
        link.Label = label
        if part is None:
            target.Visibility = False
        document.recompute()
        document.commitTransaction()
        return link
    except BaseException:
        document.abortTransaction()
        raise


def assign_member_ids(document):
    """Call only for an authorized editable source, before its controlled save."""
    metadata = document.getObject("ForgePDM_Metadata")
    if not hasattr(metadata, "ForgePDMMemberRegistry"):
        metadata.addProperty("App::PropertyString", "ForgePDMMemberRegistry", "ForgePDM")
    registry = json.loads(metadata.ForgePDMMemberRegistry or "{}")
    members = source_members(document)
    counts = {}
    for obj in members:
        identity = getattr(obj, "ForgePDMMemberId", "")
        if identity:
            counts.setdefault(identity, []).append(obj)
    for identity, copies in counts.items():
        if len(copies) > 1 and not any(o.Name == registry.get(identity) for o in copies):
            raise WorkspaceError(
                "Duplicate source member identities have no recorded owner; review copied source objects"
            )
    for obj in members:
        if not hasattr(obj, "ForgePDMMemberId"):
            obj.addProperty("App::PropertyString", "ForgePDMMemberId", "ForgePDM")
        identity = obj.ForgePDMMemberId
        if not identity or (
            len(counts.get(identity, [])) > 1 and registry.get(identity) != obj.Name
        ):
            obj.ForgePDMMemberId = str(uuid4())
        registry[obj.ForgePDMMemberId] = obj.Name
        obj.setEditorMode("ForgePDMMemberId", 1)
    metadata.ForgePDMMemberRegistry = json.dumps(registry, sort_keys=True)
    metadata.setEditorMode("ForgePDMMemberRegistry", 1)


def write_evidence(group, source_document):
    metadata = source_document.getObject("ForgePDM_Metadata")
    data = dict(
        version=2,
        members=[o.Name for o in group.Group],
        source=dict(item_id=metadata.ItemId, revision_id=metadata.RevisionId),
        targets={
            o.Name: dict(
                name=o.LinkedObject.Name, identity=getattr(o.LinkedObject, "ForgePDMMemberId", "")
            )
            for o in group.Group
        },
    )
    from . import workspace

    try:
        entry = workspace.binding(source_document.FileName, metadata.ServerUrl, False)["entry"]
    except workspace.WorkspaceError:
        entry = {}
    data["source"].update(
        {key: entry.get(key) for key in ("dataset_id", "file_id", "local_generation_id")}
    )
    setattr(group, MARKER, json.dumps(data, sort_keys=True))


def identity_source(obj):
    """Resolve recorded identity for restoration only; never validates geometry."""
    group = representation(obj)
    if group is None:
        return None
    try:
        data = json.loads(getattr(group, MARKER))
        if (
            data["version"] not in (1, 2)
            or group.TypeId != "App::Part"
            or [o.Name for o in group.Group] != data["members"]
            or not group.Group
        ):
            raise ValueError()
        target = group.Group[0].LinkedObject
        if target is None or target.TypeId != "Assembly::AssemblyObject":
            raise ValueError()
        metadata = target.Document.getObject("ForgePDM_Metadata")
        identity = [metadata.ItemId, metadata.RevisionId]
        recorded = (
            [data["source"]["item_id"], data["source"]["revision_id"]]
            if data["version"] == 2
            else json.loads(getattr(obj, "ForgePDMOccurrenceKey", "[]"))[-2:]
        )
        if recorded != identity:
            raise ValueError()
        return target
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise WorkspaceError(
            "Recorded component identity cannot be recovered; preserve its saved configuration"
        ) from error


def member_ids_current(document):
    if not any(o.TypeId == "Assembly::AssemblyObject" for o in document.Objects):
        return True
    metadata = document.getObject("ForgePDM_Metadata")
    try:
        registry = json.loads(getattr(metadata, "ForgePDMMemberRegistry", "") or "{}")
        members = source_members(document)
        identities = [getattr(o, "ForgePDMMemberId", "") for o in members]
        return (
            all(identities)
            and len(set(identities)) == len(identities)
            and all(
                registry.get(identity) == obj.Name for identity, obj in zip(identities, members)
            )
        )
    except (ValueError, TypeError):
        return False
