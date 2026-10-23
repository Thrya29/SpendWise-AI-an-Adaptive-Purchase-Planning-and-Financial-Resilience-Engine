from decimal import Decimal

import pytest

from app.domain.money import CurrencyMismatchError, Money, minor_exponent


def test_from_decimal_uses_minor_units() -> None:
    assert Money.from_decimal("1499.50", "INR").amount_minor == 149950
    assert Money.from_decimal("1499", "JPY").amount_minor == 1499
    assert Money.from_decimal("1.234", "KWD").amount_minor == 1234


def test_from_decimal_rounds_half_even() -> None:
    assert Money.from_decimal("0.125", "USD").amount_minor == 12
    assert Money.from_decimal("0.135", "USD").amount_minor == 14


def test_to_decimal_roundtrip() -> None:
    m = Money(149950, "INR")
    assert m.to_decimal() == Decimal("1499.50")
    assert str(m) == "1499.50 INR"


def test_arithmetic_and_comparison() -> None:
    a, b = Money(100, "INR"), Money(250, "INR")
    assert (a + b).amount_minor == 350
    assert (b - a).amount_minor == 150
    assert (-a).amount_minor == -100
    assert (a * 3).amount_minor == 300
    assert a < b and b > a and a <= a and b >= b


def test_currency_mismatch_rejected() -> None:
    with pytest.raises(CurrencyMismatchError):
        _ = Money(1, "INR") + Money(1, "USD")


@pytest.mark.parametrize("bad", ["abc", "NaN", "Infinity"])
def test_invalid_amounts_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        Money.from_decimal(bad, "INR")


def test_rejects_float_and_bool_and_unknown_currency() -> None:
    with pytest.raises(TypeError):
        Money(1.5, "INR")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Money(True, "INR")
    with pytest.raises(TypeError):
        _ = Money(1, "INR") * 1.5  # type: ignore[operator]
    with pytest.raises(ValueError):
        Money(1, "XYZ")


def test_currency_normalised_and_exponents() -> None:
    assert Money(1, " inr ").currency == "INR"
    assert minor_exponent("INR") == 2 and minor_exponent("JPY") == 0
    assert Money.zero("USD").amount_minor == 0
    assert Money(-1, "USD").is_negative()
