"""Native rigid component representations; source documents are never edited."""

import json

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
        if data["version"] != 1 or group.TypeId != "App::Part":
            raise ValueError()
        members = list(group.Group)
        if [o.Name for o in members] != data["members"] or not members:
            raise ValueError()
        target = members[0].LinkedObject
        if target is None or target.TypeId != "Assembly::AssemblyObject":
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
            "Incomplete ForgePDM component representation; reinsert this component"
        ) from error


def internal_names(document):
    names = set()
    for obj in document.Objects:
        if representation(obj) is not None:
            source(obj)
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
    setattr(group, MARKER, json.dumps({"version": 1, "members": members}, sort_keys=True))
    group.setEditorMode(MARKER, 1)
    group.Label = label + " representation"
    return group


def retarget(group, source_document):
    """Keep native member names so joint paths survive compatible replacements."""
    document = group.Document
    previous = {link.LinkedObject.Name: link for link in group.Group}
    members = []
    for original in source_members(source_document):
        link = previous.pop(original.Name, None)
        if link is None:
            link = document.addObject("App::Link", "ComponentMember")
        link.setLink(original)
        link.Placement = original.Placement
        link.Visibility = original.Visibility
        members.append(link)
    group.Group = members
    for link in previous.values():
        document.removeObject(link.Name)
    setattr(
        group,
        MARKER,
        json.dumps({"version": 1, "members": [o.Name for o in members]}, sort_keys=True),
    )
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
