from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.fx import RateTable, RateUnavailableError, parse_rate
from app.domain.money import Money

TABLE = RateTable(
    pivot="EUR",
    rates={"INR": Decimal("106.249"), "USD": Decimal("1.1205"), "JPY": Decimal("175.97")},
    as_of=date(2026, 10, 22),
    source="ECB via Frankfurter",
)


def test_cross_rates() -> None:
    assert TABLE.cross("EUR", "INR") == Decimal("106.249")
    assert TABLE.cross("INR", "INR") == 1
    usd_inr = TABLE.cross("USD", "INR")
    assert abs(usd_inr - Decimal("94.8228469433288710397144132")) < Decimal("1e-20")


def test_convert_is_exact_and_rounds_half_even() -> None:
    assert TABLE.convert(Money(100, "USD"), "INR") == Money(9482, "INR")  # $1 -> ₹94.82
    assert TABLE.convert(Money(10_000, "EUR"), "JPY") == Money(17_597, "JPY")  # zero-decimal
    assert TABLE.convert(Money(150_000, "INR"), "INR") == Money(150_000, "INR")
    assert TABLE.convert(Money(-100, "USD"), "INR") == Money(-9482, "INR")


def test_unsupported_pairs_raise() -> None:
    assert TABLE.supports("INR") and TABLE.supports("EUR") and not TABLE.supports("AED")
    with pytest.raises(RateUnavailableError):
        TABLE.convert(Money(100, "AED"), "INR")
    with pytest.raises(ValueError):
        RateTable("EUR", {"INR": Decimal(0)}, date(2026, 1, 1), "x")


def test_parse_rate() -> None:
    assert parse_rate(1.1205) == Decimal("1.1205")
    assert parse_rate("106.249") == Decimal("106.249")
    for bad in ("abc", "-1", "0", "NaN", None):
        with pytest.raises(ValueError):
            parse_rate(bad)


@given(st.integers(-(10**12), 10**12))
def test_round_trip_error_is_bounded(minor: int) -> None:
    there = TABLE.convert(Money(minor, "USD"), "INR")
    back = TABLE.convert(there, "USD")
    # One rounding in each direction: at most one cent of drift.
    assert abs(back.amount_minor - minor) <= 1
