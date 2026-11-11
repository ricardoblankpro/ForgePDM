from decimal import Decimal

import pytest

from freecad.forgepdm.mass_display import format_mass
from freecad.forgepdm.assembly_mass import summary


@pytest.mark.parametrize(
    "value,expected",
    [
        ("0", "0"),
        ("1.4580623990476929862", "1.458"),
        ("2.500", "2.5"),
        ("0.0009", "<0.001"),
        ("0.001", "0.001"),
        ("1.2345", "1.235"),
        ("999.9995", "1000"),
        ("1E-20", "<0.001"),
        ("1E+25", "10000000000000000000000000"),
    ],
)
def test_rounding_preserves_evidence(value, expected):
    evidence = Decimal(value)
    assert format_mass(evidence) == expected
    assert evidence == Decimal(value)


def test_missing_mass_keeps_subtotal_and_warning():
    text = summary(
        dict(
            mass_kg=None,
            known_mass_kg="1.4580623990476929862",
            contains_cad_estimates=True,
            issues=[],
        )
    )
    assert "Known subtotal: 1.458 kg" in text
    assert "estimated" in text
