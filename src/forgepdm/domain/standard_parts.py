"""Version 1 standard-part specification contract; no CAD runtime dependencies."""

import json
from decimal import Decimal, InvalidOperation

PARAMETERS = (
    "Type",
    "Diameter",
    "LeftHanded",
    "Length",
    "LengthCustom",
    "Width",
    "DiameterCustom",
    "PitchCustom",
    "Tcode",
    "Blind",
    "ScrewLength",
    "SlotWidth",
    "ExternalDiam",
    "KeySize",
)


def scalar(value):
    if not isinstance(value, (str, int, float, bool)):
        raise ValueError("Standard-part parameters must be scalar values")
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value).strip().casefold().replace("″", "in")
    if not text or len(text) > 200 or any(ord(c) < 32 for c in text):
        raise ValueError("Invalid standard-part parameter")
    try:
        number = Decimal(text)
        if not number.is_finite():
            raise ValueError("Nonfinite standard-part parameter")
        if abs(number.adjusted()) > 30:
            raise ValueError("Standard-part number exceeds supported bounds")
        return format(number.normalize(), "f")
    except InvalidOperation:
        return text


def geometry(value):
    if (
        not isinstance(value, dict)
        or not value
        or set(value) - set(PARAMETERS)
        or "Type" not in value
    ):
        raise ValueError("Invalid fastener geometry specification")
    return {key: scalar(val) for key, val in sorted(value.items())}


def specification(value):
    if not isinstance(value, dict) or set(value) != {"geometry", "material", "grade", "finish"}:
        raise ValueError("Specification requires geometry, material, grade and finish")
    return dict(
        geometry=geometry(value["geometry"]),
        **{
            key: None if value[key] is None else scalar(value[key])
            for key in ("material", "grade", "finish")
        },
    )


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
