"""Read-only marker positions and captions for frozen drawing balloon diagnostics."""

import math


def page_position(balloon):
    """Return bubble center in page millimeters, including projection-group offsets.

    TechDraw bubble X/Y are scaled offsets from the parent view. Its rotation
    applies to the projected geometry/arrow, not the bubble's X/Y offsets.
    """
    source = balloon.SourceView
    if source is None:
        raise ValueError("The balloon has no source view")
    x, y = float(source.X), float(source.Y)
    if source.TypeId == "TechDraw::DrawProjGroupItem":
        group = next(
            (
                obj
                for obj in source.InList
                if obj.TypeId == "TechDraw::DrawProjGroup" and source in obj.Views
            ),
            None,
        )
        if group is None:
            raise ValueError("The projected view has no owning group")
        x, y = x + float(group.X), y + float(group.Y)
    scale = float(source.getScale())
    point = x + float(balloon.X) * scale, y + float(balloon.Y) * scale
    if not all(math.isfinite(v) for v in (*point, scale)) or scale <= 0:
        raise ValueError("The balloon has invalid page coordinates")
    return point


def caption(balloon):
    position = getattr(balloon, "PDMBOMPosition", "") or balloon.Text
    return "{} · BOM {}".format(balloon.Label, position)
