"""Unit-safe gross material requirement arithmetic, independent of CAD and storage."""

from decimal import Decimal, InvalidOperation

# Factors convert supported units to the canonical unit of their dimension.
UNITS = {
    "ea": ("ea", Decimal(1)),
    "mm": ("m", Decimal("0.001")),
    "cm": ("m", Decimal("0.01")),
    "m": ("m", Decimal(1)),
    "mm2": ("m2", Decimal("0.000001")),
    "m2": ("m2", Decimal(1)),
    "g": ("kg", Decimal("0.001")),
    "kg": ("kg", Decimal(1)),
}


def decimal_quantity(value, *, allow_zero=False):
    """Reject non-finite values and avoid binary floating-point arithmetic."""
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError("quantity must be a finite decimal") from error
    if not result.is_finite() or result < 0 or (result == 0 and not allow_zero):
        raise ValueError(
            "quantity must be positive" if not allow_zero else "quantity must be nonnegative"
        )
    if result and (result.adjusted() > 18 or result.adjusted() < -100 or len(result.as_tuple().digits) > 128):
        raise ValueError("quantity exceeds supported precision or magnitude")
    return result


def normalize_quantity(quantity, unit):
    if unit not in UNITS:
        raise ValueError("unsupported material unit")
    canonical, factor = UNITS[unit]
    return decimal_quantity(quantity) * factor, canonical


def gross_requirement(quantity, unit, parent_quantity, allowance_percent="0"):
    """Calculate consumption including a per-unit percentage allowance."""
    normalized, canonical = normalize_quantity(quantity, unit)
    parents = decimal_quantity(parent_quantity)
    allowance = decimal_quantity(allowance_percent, allow_zero=True)
    return normalized * parents * (1 + allowance / 100), canonical


def finished_mass(volume_mm3, density_kg_m3):
    """Return kg for one explicitly validated solid volume and catalog density."""
    volume = decimal_quantity(volume_mm3, allow_zero=True)
    density = decimal_quantity(density_kg_m3)
    return volume * density / Decimal(1000000000)
