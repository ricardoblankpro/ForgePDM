"""Exact fastener specification keys and explicitly quantified supplier mass."""

import hashlib
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from forgepdm.domain.standard_parts import encode, specification


def specification_key(value):
    return hashlib.sha256(encode(specification(value)).encode()).hexdigest()


def mass_kg(mass, unit, quantity):
    try:
        if len(str(mass)) > 100 or len(str(quantity)) > 100:
            raise ValueError("Supplier quantities are too long")
        value, count = Decimal(str(mass)), Decimal(str(quantity))
        factor = {"g": Decimal("0.001"), "kg": Decimal(1)}[unit]
        if (
            not value.is_finite()
            or not count.is_finite()
            or not 1 <= count <= 1000000
            or count != count.to_integral_value()
        ):
            raise ValueError("Invalid supplier mass quantity")
        if not 0 < value <= 1000000 or value.adjusted() < -30:
            raise ValueError("Invalid supplier mass")
        result = value * factor / count
        if not Decimal("1e-12") <= result <= 10000:
            raise ValueError("Supplier unit mass outside supported bounds")
        return format(result.normalize(), "f")
    except (InvalidOperation, KeyError, TypeError) as error:
        raise ValueError("Use a positive mass in g or kg with an explicit piece count") from error


def source_url(value):
    if not isinstance(value, str) or len(value) > 2000 or any(ord(c) < 32 for c in value):
        raise ValueError("Invalid supplier source URL")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Supplier source must be an HTTPS URL")
    return value


# Reviewed factual density values from FreeCAD 1.1.4 standard physical cards.
# These are explicit estimate surrogates, not certification of a fastener alloy.
DENSITY_REFERENCES = {
    "steel": ("Steel-Generic", "90bbd8ef-8623-4d78-b3bf-e0bdb9b74dd3", "7900"),
    "carbon steel": ("Steel-C15", "06ae5c92-de7b-46c9-984d-4dd87964bc5c", "7800"),
    "alloy steel": ("Steel-20NiCrMo2", "1c759697-7aef-4a14-92c5-5bf84b99a4f0", "7800"),
    "stainless steel a2": ("Steel-X5CrNi18-10", "e5329208-0c38-47ec-8c59-e7bf6a35801d", "7800"),
    "stainless steel a4": ("Steel-X5CrNiMo17-12-2", "7625a484-96de-438d-b251-2b71044cfa88", "7800"),
    "aluminium": ("Aluminum-Generic", "9bf060e9-1663-44a2-88e2-2ff6ee858efe", "2700"),
    "aluminum": ("Aluminum-Generic", "9bf060e9-1663-44a2-88e2-2ff6ee858efe", "2700"),
    "copper": ("Copper-Generic", "6c03899d-496e-4c60-a41b-3d66f2337fb9", "8960"),
}


def density_reference(spec):
    entry = DENSITY_REFERENCES.get(spec.get("material")) if spec else None
    if not entry:
        return None
    name, uuid, density = entry
    return {
        "version": 1,
        "material": spec["material"],
        "name": name,
        "source_uuid": uuid,
        "density_kg_m3": density,
        "basis": "FreeCAD 1.1.4 reference card; approximate material surrogate",
    }


def mass_token(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def estimate_mass(volume, density):
    try:
        if len(str(volume)) > 100:
            raise ValueError("Invalid CAD volume")
        value = Decimal(str(volume))
        if not value.is_finite() or not Decimal("1e-9") <= value <= Decimal("1e12"):
            raise ValueError("Invalid CAD volume")
        return mass_kg(value * Decimal(density) / Decimal("1e9"), "kg", 1)
    except InvalidOperation as error:
        raise ValueError("Invalid CAD volume") from error
