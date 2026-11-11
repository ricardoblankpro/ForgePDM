"""Display-only mass rounding; published evidence retains full precision."""

from decimal import Decimal, ROUND_HALF_UP, localcontext


def format_mass(value):
    number = Decimal(str(value))
    if 0 < number < Decimal("0.001"):
        return "<0.001"
    with localcontext() as context:
        context.prec = max(28, len(number.as_tuple().digits) + abs(number.adjusted()) + 4)
        rounded = number.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    return format(rounded, "f").rstrip("0").rstrip(".") or "0"
