"""Optional Fasteners Workbench adapter, executed only on the GUI thread."""

import json
import re
import sys
from uuid import UUID, uuid4

from .standard_contract import PARAMETERS, encode, geometry
from .workspace import WorkspaceError

ASSOCIATION = "PDMStandardAssociation"


def recognized(obj):
    proxy = getattr(obj, "Proxy", None)
    return getattr(obj, "TypeId", "") == "Part::FeaturePython" and any(
        cls.__module__ == "FastenersCmd" and cls.__name__ == "FSScrewObject"
        for cls in type(proxy).__mro__
    )


def extract(obj):
    if not recognized(obj):
        raise WorkspaceError("Fasteners Workbench is missing or this fastener proxy is unsupported")
    module = sys.modules.get("FastenersCmd")
    declared = getattr(module, "FastenerAttribs", PARAMETERS)
    if set(declared) - set(PARAMETERS) - {"Thread", "MatchOuter"}:
        raise WorkspaceError("Fasteners parameters changed; update the ForgePDM adapter")
    values = {}
    for name in PARAMETERS:
        if hasattr(obj, name):
            value = getattr(obj, name)
            values[name] = value.Value if hasattr(value, "Value") else value
    return geometry(values)


def objects(document):
    return [
        obj
        for obj in getattr(document, "Objects", ())
        if getattr(obj, "TypeId", "") == "Part::FeaturePython"
        and (recognized(obj) or hasattr(obj, ASSOCIATION))
    ]


def association(obj):
    try:
        value = json.loads(getattr(obj, ASSOCIATION, ""))
        if not isinstance(value, dict) or value.get("version") != 1:
            return None
        UUID(value["occurrence_id"])
        UUID(value["revision_id"])
        return value if geometry(value["geometry"]) == extract(obj) else None
    except (ValueError, KeyError, TypeError):
        return None


def associate(obj, revision_id, occurrence_id=None):
    if not hasattr(obj, ASSOCIATION):
        obj.addProperty("App::PropertyString", ASSOCIATION, "ForgePDM")
    setattr(
        obj,
        ASSOCIATION,
        encode(
            dict(
                version=1,
                generator_version=generator_version(),
                occurrence_id=occurrence_id or str(uuid4()),
                revision_id=str(UUID(revision_id)),
                geometry=extract(obj),
            )
        ),
    )


def capture(document):
    result, seen = [], set()
    for obj in objects(document):
        entry = association(obj)
        if entry is None:
            raise WorkspaceError(
                "Fastener '{}' needs catalog association; Upload or Check In first".format(obj.Name)
            )
        if entry["occurrence_id"] in seen:
            raise WorkspaceError(
                "Copied fasteners need distinct occurrence identities; Upload first"
            )
        seen.add(entry["occurrence_id"])
        result.append(
            dict(
                object_name=obj.Name,
                occurrence_id=entry["occurrence_id"],
                revision_id=entry["revision_id"],
                geometry=entry["geometry"],
            )
        )
    return sorted(result, key=lambda row: row["object_name"])


def attachment(obj):
    base = getattr(obj, "BaseObject", None)
    if not base:
        return None
    target, subs = base
    if isinstance(subs, str):
        subs = [subs]
    local = getattr(obj, "Document", None) is not None and target.Document is obj.Document
    # Native selection may include the local Assembly/component/feature path.
    # Its external files are pinned through the existing managed links. Keep
    # direct external BaseObject references on their narrower manifest contract.
    pattern = (
        r"(?:[A-Za-z_][A-Za-z0-9_]*\.)*(?:Edge|Face|Vertex)[1-9][0-9]*"
        if local
        else r"(?:Edge|Face|Vertex)[1-9][0-9]*"
    )
    if (
        len(subs) != 1
        or not isinstance(subs[0], str)
        or len(subs[0]) > 1000
        or re.fullmatch(pattern, subs[0]) is None
    ):
        raise WorkspaceError(
            "Fastener '{}' needs one explicit edge, face or vertex; qualified paths are supported within its own document".format(
                obj.Name
            )
        )
    if not subelement_exists(target, subs[0]):
        raise WorkspaceError("Fastener attachment subelement cannot be resolved")
    return target, subs[0]


def describe(value):
    """Human-readable identity for association review."""
    dimensions = value.get("geometry", value)
    fields = []
    for key, val in dimensions.items():
        if key == "LengthCustom" and dimensions.get("Length") != "custom":
            continue
        if key == "LeftHanded" and val == "false":
            continue
        label = re.sub(r"([a-z])([A-Z])", r"\1 \2", key)
        fields.append(
            label + ": " + (str(val).upper() if key in ("Type", "Diameter") else str(val))
        )
    if "geometry" in value:
        fields.extend(
            key.title() + ": " + (value[key] or "Unknown")
            for key in ("material", "grade", "finish")
        )
    return "; ".join(fields)


def generator_version():
    """Record optional generator provenance without importing the workbench."""
    from pathlib import Path
    from xml.etree import ElementTree

    module = sys.modules.get("FastenersCmd")
    filename = getattr(module, "__file__", None)
    if filename:
        try:
            return (
                ElementTree.parse(Path(filename).parent / "package.xml").findtext("version")
                or "unknown"
            )
        except (OSError, ElementTree.ParseError):
            pass
    return "unknown"


def subelement_exists(target, subelement):
    shape = target.getSubObject(subelement)
    return shape is not None and hasattr(shape, "isNull") and not shape.isNull()
