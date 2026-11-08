from decimal import Decimal

import pytest

from forgepdm.domain.materials import finished_mass, gross_requirement, normalize_quantity


def test_nested_occurrence_consumption_and_allowance():
    assert gross_requirement("400", "mm", 2 * 3) == (Decimal("2.4"), "m")
    assert gross_requirement("400", "mm", 6, "10") == (Decimal("2.64"), "m")


def test_area_and_mass_units():
    assert normalize_quantity("1000000", "mm2") == (Decimal(1), "m2")
    assert normalize_quantity("500", "g") == (Decimal("0.5"), "kg")
    assert finished_mass("1000000", "7850") == Decimal("7.85")


@pytest.mark.parametrize("quantity", ["NaN", "Infinity", "-1", "0", "bad"])
def test_invalid_consumption(quantity):
    with pytest.raises(ValueError):
        gross_requirement(quantity, "m", 1)


def test_invalid_unit_and_allowance():
    with pytest.raises(ValueError):
        normalize_quantity(1, "sheet")
    with pytest.raises(ValueError):
        gross_requirement(1, "m", 1, "-1")
