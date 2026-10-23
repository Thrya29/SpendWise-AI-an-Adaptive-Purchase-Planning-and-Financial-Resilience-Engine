"""Exact money arithmetic.

All monetary amounts are stored as integers in the currency's minor unit
(e.g. paise for INR, cents for USD, yen for JPY). Floats are never used.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

# ISO 4217 minor-unit exponents that differ from the default of 2.
_NON_DEFAULT_EXPONENTS: dict[str, int] = {
    "BIF": 0, "CLP": 0, "DJF": 0, "GNF": 0, "ISK": 0, "JPY": 0, "KMF": 0, "KRW": 0,
    "PYG": 0, "RWF": 0, "UGX": 0, "UYI": 0, "VND": 0, "VUV": 0, "XAF": 0, "XOF": 0,
    "XPF": 0, "BHD": 3, "IQD": 3, "JOD": 3, "KWD": 3, "LYD": 3, "OMR": 3, "TND": 3,
}  # fmt: skip

SUPPORTED_CURRENCIES: frozenset[str] = frozenset(
    {
        "INR", "USD", "EUR", "GBP", "AED", "SGD", "AUD", "CAD", "JPY", "CHF", "CNY",
        "HKD", "NZD", "SAR", "QAR", "KWD", "BHD", "OMR", "MYR", "THB", "IDR", "PHP",
        "LKR", "NPR", "BDT", "PKR", "ZAR", "SEK", "NOK", "DKK", "KRW", "BRL", "MXN",
    }
)  # fmt: skip


class CurrencyMismatchError(ValueError):
    """Raised when arithmetic is attempted across different currencies."""


def minor_exponent(currency: str) -> int:
    return _NON_DEFAULT_EXPONENTS.get(currency, 2)


def validate_currency(currency: str) -> str:
    code = currency.strip().upper()
    if code not in SUPPORTED_CURRENCIES:
        raise ValueError(f"Unsupported currency: {currency!r}")
    return code


@dataclass(frozen=True, slots=True)
class Money:
    amount_minor: int
    currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.amount_minor, int) or isinstance(self.amount_minor, bool):
            raise TypeError("amount_minor must be an int")
        object.__setattr__(self, "currency", validate_currency(self.currency))

    @classmethod
    def zero(cls, currency: str) -> Money:
        return cls(0, currency)

    @classmethod
    def from_decimal(cls, value: Decimal | str | int, currency: str) -> Money:
        """Convert a major-unit decimal (e.g. "1499.50") into minor units.

        Rounds half-to-even when more precision is supplied than the currency supports.
        """
        try:
            dec = Decimal(value) if not isinstance(value, Decimal) else value
        except InvalidOperation as exc:
            raise ValueError(f"Invalid amount: {value!r}") from exc
        if not dec.is_finite():
            raise ValueError("Amount must be finite")
        code = validate_currency(currency)
        scaled = (dec * (Decimal(10) ** minor_exponent(code))).quantize(
            Decimal(1), rounding=ROUND_HALF_EVEN
        )
        return cls(int(scaled), code)

    def to_decimal(self) -> Decimal:
        return Decimal(self.amount_minor).scaleb(-minor_exponent(self.currency))

    def _check(self, other: Money) -> None:
        if self.currency != other.currency:
            raise CurrencyMismatchError(f"{self.currency} != {other.currency}")

    def __add__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.amount_minor + other.amount_minor, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.amount_minor - other.amount_minor, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.amount_minor, self.currency)

    def __mul__(self, factor: int) -> Money:
        if not isinstance(factor, int) or isinstance(factor, bool):
            raise TypeError("Money can only be multiplied by an int")
        return Money(self.amount_minor * factor, self.currency)

    def __lt__(self, other: Money) -> bool:
        self._check(other)
        return self.amount_minor < other.amount_minor

    def __le__(self, other: Money) -> bool:
        self._check(other)
        return self.amount_minor <= other.amount_minor

    def __gt__(self, other: Money) -> bool:
        self._check(other)
        return self.amount_minor > other.amount_minor

    def __ge__(self, other: Money) -> bool:
        self._check(other)
        return self.amount_minor >= other.amount_minor

    def is_negative(self) -> bool:
        return self.amount_minor < 0

    def __str__(self) -> str:
        return f"{self.to_decimal():.{minor_exponent(self.currency)}f} {self.currency}"
