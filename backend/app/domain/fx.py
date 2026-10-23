"""Exact currency conversion from a table of reference rates.

Rates are quoted against one pivot currency (ECB publishes EUR -> X). A cross rate
A -> B is ``rate[B] / rate[A]``. Conversion works on integer minor units with
banker's rounding, so results are reproducible to the paisa/cent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext

from app.domain.money import Money, minor_exponent, validate_currency


class RateUnavailableError(LookupError):
    """No reference rate exists for the requested pair."""


@dataclass(frozen=True, slots=True)
class RateTable:
    pivot: str
    rates: dict[str, Decimal]  # pivot -> currency
    as_of: date
    source: str

    def __post_init__(self) -> None:
        for code, rate in self.rates.items():
            if rate <= 0:
                raise ValueError(f"Rate for {code} must be positive")

    def _rate(self, code: str) -> Decimal:
        if code == self.pivot:
            return Decimal(1)
        try:
            return self.rates[code]
        except KeyError as exc:
            raise RateUnavailableError(code) from exc

    def supports(self, code: str) -> bool:
        return code == self.pivot or code in self.rates

    def cross(self, base: str, quote: str) -> Decimal:
        """Units of ``quote`` per one unit of ``base``."""
        base, quote = validate_currency(base), validate_currency(quote)
        if base == quote:
            return Decimal(1)
        with localcontext() as ctx:
            ctx.prec = 28
            return self._rate(quote) / self._rate(base)

    def convert(self, money: Money, to: str) -> Money:
        to = validate_currency(to)
        if money.currency == to:
            return money
        rate = self.cross(money.currency, to)
        with localcontext() as ctx:
            ctx.prec = 40
            major = Decimal(money.amount_minor).scaleb(-minor_exponent(money.currency)) * rate
            minor = (major.scaleb(minor_exponent(to))).quantize(Decimal(1), ROUND_HALF_EVEN)
        return Money(int(minor), to)


def parse_rate(value: object) -> Decimal:
    """Parse a provider rate (number or string) into a positive Decimal."""
    try:
        rate = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid rate: {value!r}") from exc
    if not rate.is_finite() or rate <= 0:
        raise ValueError(f"Invalid rate: {value!r}")
    return rate
