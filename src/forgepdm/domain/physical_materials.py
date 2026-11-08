"""Portable density snapshots and source-pinned mass validation without CAD imports."""

import hashlib
import json
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def snapshot(value):
    if not isinstance(value, dict) or set(value) - {
        "version",
        "source_uuid",
        "name",
        "density_kg_m3",
        "author",
        "license",
    }:
        raise ValueError("invalid physical material snapshot")
    if value.get("version") != 1:
        raise ValueError("unsupported physical material version")
    try:
        source = str(UUID(value["source_uuid"]))
    except (KeyError, ValueError, TypeError, AttributeError) as error:
        raise ValueError("invalid source material UUID") from error
    if not isinstance(value.get("name"), str):
        raise ValueError("invalid physical material name")  # noqa: TRY004
    name = value["name"].strip()
    if not name or len(name) > 200:
        raise ValueError("physical material name is required")
    try:
        density = Decimal(str(value["density_kg_m3"]))
    except Exception as error:
        raise ValueError("invalid density") from error
    if not density.is_finite() or not 0 < density <= 1000000 or density.adjusted() < -100:
        raise ValueError("density must be positive kg/m3")
    result = {
        "version": 1,
        "source_uuid": source,
        "name": name,
        "density_kg_m3": format(density.normalize(), "f"),
    }
    for key in ("author", "license"):
        text = value.get(key, "")
        if not isinstance(text, str) or len(text) > 1000:
            raise ValueError("invalid material attribution")
        result[key] = text
    return result


def fingerprint(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def native_uuid(value):
    return str(uuid5(NAMESPACE_URL, "forgepdm-density-v1:" + fingerprint(value)))
