"""Read-only model-space picking from native unscaled balloon origins."""

import hashlib
import json
import math

from .geometry_fingerprint import PROFILE, fingerprint

TOLERANCE_MM = 0.25
SUPPORTED = {"TechDraw::DrawViewPart", "TechDraw::DrawProjGroupItem"}


def revision(obj):
    from . import fasteners

    association = fasteners.association(obj) if hasattr(obj, "PDMStandardAssociation") else None
    if association:
        return association["revision_id"]
    if obj.TypeId in ("App::Link", "Assembly::AssemblyLink"):
        target = obj.getLinkedObject(True)
        if target and target.Document is not obj.Document:
            metadata = target.Document.getObject("ForgePDM_Metadata")
            if metadata:
                return metadata.RevisionId
    return None


def components(view):
    result, seen = [], set()

    def walk(obj):
        if obj is None or (obj.Document.Name, obj.Name) in seen:
            return
        seen.add((obj.Document.Name, obj.Name))
        rid = revision(obj)
        if rid or not getattr(obj, "Group", None):
            shape = getattr(obj, "Shape", None)
            if shape is not None and not shape.isNull():
                shape = shape.copy()
                if hasattr(obj, "getGlobalPlacement"):
                    shape.Placement = (
                        obj.getGlobalPlacement()
                        .multiply(obj.Placement.inverse())
                        .multiply(shape.Placement)
                    )
                result.append((obj, rid, shape))
            return
        for child in obj.Group:
            walk(child)

    for obj in list(view.Source) + list(getattr(view, "XSource", [])):
        walk(obj[0] if isinstance(obj, tuple) else obj)
    return result


def pick(balloon):
    import FreeCAD as App
    import Part

    view = balloon.SourceView
    if view is None or view.TypeId not in SUPPORTED or view.Perspective:
        raise ValueError(
            "Automatic balloons support ordinary and projection-group views without perspective; use manual linking"
        )
    scale = float(view.Scale)
    x, y = float(balloon.OriginX), float(balloon.OriginY)
    if scale <= 0 or not all(math.isfinite(v) for v in (scale, x, y)):
        raise ValueError("Invalid drawing scale or arrow position")
    # Native OriginX/Y are unscaled and unrotated. projectPoint uses the same basis.
    basis = [view.projectPoint(App.Vector(*v)) for v in [(1, 0, 0), (0, 1, 0), (0, 0, 1)]]
    axis_x = App.Vector(*(v.x for v in basis))
    axis_y = App.Vector(*(v.y for v in basis))
    direction = axis_x.cross(axis_y)
    direction.normalize()
    center = view.getGeometricCenter()
    point = center + axis_x * x + axis_y * y
    rows = components(view)
    span = (
        max(
            [1.0]
            + [
                (shape.BoundBox.Center - point).Length + shape.BoundBox.DiagonalLength
                for _, _, shape in rows
            ]
        )
        + 1
    )
    ray = Part.makeLine(point - direction * span, point + direction * span)
    hits = []
    for obj, rid, shape in rows:
        if ray.distToShape(shape)[0] <= TOLERANCE_MM / scale:
            hits.append((obj, rid))
    return hits


def evidence(balloon, *, legacy=False):
    """Snapshot geometry and view configuration; no mutable visual row index."""
    view = balloon.SourceView
    rows = components(view)
    value = {
        "view": view.Name,
        "type": view.TypeId,
        "origin": [float(balloon.OriginX), float(balloon.OriginY)],
        "direction": list(view.Direction),
        "x_direction": list(view.XDirection),
        "scale": float(view.Scale),
        "rotation": float(view.Rotation),
        "perspective": view.Perspective,
        "components": [
            (
                obj.Document.Name,
                obj.Name,
                rid,
                hashlib.sha256(shape.exportBrepToString().encode()).hexdigest()
                if legacy
                else fingerprint(shape.exportBrepToString()),
            )
            for obj, rid, shape in rows
        ],
    }
    # Document names change on isolated retrieval; occurrence names remain local.
    value["components"] = [list(row[1:]) for row in value["components"]]
    if not legacy:
        value["fingerprint"] = PROFILE
    return value


def candidates(balloon, data):
    from .drawing_balloons import entries

    hits = pick(balloon)
    if not hits:
        raise ValueError("The arrow does not touch component geometry within 0.25 mm on paper")
    if any(rid is None for _, rid in hits):
        raise ValueError("The arrow touches geometry without a pinned ForgePDM component identity")
    lines = entries(data)
    if any(not any(line["component_revision_id"] == rid for line in lines) for _, rid in hits):
        raise ValueError("A touched component is absent from the frozen BOM; update Drawing BOM")
    return [
        (obj, line)
        for obj, rid in hits
        for line in entries(data)
        if line["component_revision_id"] == rid
    ]


def signature(balloon):
    return json.dumps(evidence(balloon), sort_keys=True)
