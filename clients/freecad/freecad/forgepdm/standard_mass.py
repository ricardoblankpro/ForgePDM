"""Read-only Fasteners solid measurement; density references come from the API."""

import hashlib
import math

from . import fasteners


def estimate(obj, current):
    context = current.get("estimate_context")
    if current.get("mass_kg") is not None or not context or obj is None:
        return None
    geometry = fasteners.extract(obj)
    if geometry != context["geometry"]:
        return None
    shape = obj.Shape
    if shape.isNull() or not shape.isValid() or len(shape.Solids) != 1:
        return None
    volume = float(shape.Volume)
    if not math.isfinite(volume) or not 1e-9 <= volume <= 1e12:
        return None
    brep = shape.exportBrepToString().encode()
    if len(brep) > 8 * 1024 * 1024:
        return None
    thread = getattr(obj, "Thread", None)
    return {
        "method": "cad_estimate",
        "expected_token": current["token"],
        "geometry": geometry,
        "volume_mm3": format(volume, ".17g"),
        "shape_sha256": hashlib.sha256(brep).hexdigest(),
        "thread_mode": "modeled"
        if thread is True
        else "simplified"
        if thread is False
        else "unknown",
        "generator_version": fasteners.generator_version(),
    }


def label(value):
    return {
        "supplier_reference": "Supplier reference",
        "cad_estimate": "Estimated from CAD",
        "manual": "Manual entry",
    }.get(value.get("status"), "Mass unavailable")
