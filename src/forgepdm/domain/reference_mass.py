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
