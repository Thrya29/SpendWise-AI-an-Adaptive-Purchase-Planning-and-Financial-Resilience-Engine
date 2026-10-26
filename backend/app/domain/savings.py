"""Deposit and savings calculators. Exact Decimal arithmetic on minor units; no floats.

Conventions (Indian banks; adjustable by the caller):
* Fixed deposits of 6 months or more compound quarterly; shorter ones pay simple interest.
* Breaking a deposit early earns the rate for the period actually held, minus a penalty
  (commonly 0.5-1 percentage point), never below zero.
* Savings accounts are modelled as monthly-rested interest credited quarterly.
Results are educational estimates: banks' exact day counts and TDS are not modelled.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, localcontext

QUARTERLY_FROM_MONTHS = 6


def _q(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), ROUND_HALF_EVEN))


def _check(principal: int, months: int, rate_percent: Decimal) -> None:
    if principal <= 0:
        raise ValueError("Principal must be positive")
    if not 1 <= months <= 120:
        raise ValueError("Tenure must be 1-120 months")
    if not Decimal(0) <= rate_percent <= Decimal(20):
        raise ValueError("Rate must be between 0% and 20% a year")


def fd_maturity(principal: int, rate_percent: Decimal, months: int) -> int:
    """Maturity value in minor units."""
    _check(principal, months, rate_percent)
    rate = rate_percent / Decimal(100)
    with localcontext() as ctx:
        ctx.prec = 40
        if months < QUARTERLY_FROM_MONTHS:
            return _q(Decimal(principal) * (1 + rate * Decimal(months) / 12))
        quarters = Decimal(months) / 3
        return _q(Decimal(principal) * (1 + rate / 4) ** quarters)


@dataclass(frozen=True, slots=True)
class Premature:
    held_months: int
    effective_rate_percent: Decimal
    payout: int
    interest_lost: int  # versus holding to maturity, at the same booking rate


def premature_payout(
    principal: int,
    booked_rate_percent: Decimal,
    tenure_months: int,
    held_months: int,
    *,
    rate_for_held_period_percent: Decimal | None = None,
    penalty_percent: Decimal = Decimal("1.0"),
) -> Premature:
    """Payout when breaking an FD after ``held_months``.

    Banks apply the rate they offer for the period actually held (often lower than the
    booked rate) minus a penalty. If that rate is not supplied, the booked rate is used.
    """
    _check(principal, tenure_months, booked_rate_percent)
    if not 0 <= held_months <= tenure_months:
        raise ValueError("Held period must be within the tenure")
    if penalty_percent < 0:
        raise ValueError("Penalty cannot be negative")
    base = (
        rate_for_held_period_percent
        if rate_for_held_period_percent is not None
        else (booked_rate_percent)
    )
    effective = max(Decimal(0), base - penalty_percent)
    payout = principal if held_months == 0 else fd_maturity(principal, effective, held_months)
    full = fd_maturity(principal, booked_rate_percent, tenure_months)
    return Premature(held_months, effective, payout, full - payout)


def savings_balance(principal: int, rate_percent: Decimal, months: int) -> int:
    """Balance after ``months`` in a savings account (interest credited every 3 months)."""
    _check(principal, months, rate_percent)
    monthly = rate_percent / Decimal(100) / 12
    balance = Decimal(principal)
    accrued = Decimal(0)
    with localcontext() as ctx:
        ctx.prec = 40
        for m in range(1, months + 1):
            accrued += balance * monthly
            if m % 3 == 0:
                balance += accrued.quantize(Decimal(1), ROUND_HALF_EVEN)
                accrued = Decimal(0)
    return _q(balance)


# ---------- Gold ----------
TROY_OUNCE_GRAMS = Decimal("31.1034768")
PURITY = {"24K": Decimal("0.999"), "22K": Decimal("0.916"), "18K": Decimal("0.750"),
          "14K": Decimal("0.585")}  # fmt: skip


@dataclass(frozen=True, slots=True)
class JewelleryBill:
    gold_value: int
    making_charges: int
    hallmark_fee: int
    gst: int
    total: int
    effective_per_gram: int


def per_gram_from_ounce(price_per_ounce_minor: int) -> int:
    return _q(Decimal(price_per_ounce_minor) / TROY_OUNCE_GRAMS)


def jewellery_bill(
    *,
    rate_24k_per_gram: int,
    weight_grams: Decimal,
    purity: str,
    making_percent: Decimal | None = None,
    making_per_gram: int | None = None,
    gst_percent: Decimal = Decimal(3),
    hallmark_fee: int = 0,
) -> JewelleryBill:
    """A jewellery bill split into gold value, making charges, hallmarking and GST.

    GST in India is 3% on gold value plus making charges (the default; adjustable).
    """
    if purity not in PURITY:
        raise ValueError(f"Purity must be one of {', '.join(PURITY)}")
    if rate_24k_per_gram <= 0 or weight_grams <= 0:
        raise ValueError("Rate and weight must be positive")
    if (making_percent is None) == (making_per_gram is None):
        raise ValueError("Give making charges either as a percentage or per gram")
    gold = Decimal(rate_24k_per_gram) * PURITY[purity] / PURITY["24K"] * weight_grams
    making = (
        gold * making_percent / 100
        if making_percent is not None
        else Decimal(making_per_gram or 0) * weight_grams
    )
    gst = (gold + making) * gst_percent / 100
    total = _q(gold) + _q(making) + hallmark_fee + _q(gst)
    return JewelleryBill(
        gold_value=_q(gold),
        making_charges=_q(making),
        hallmark_fee=hallmark_fee,
        gst=_q(gst),
        total=total,
        effective_per_gram=_q(Decimal(total) / weight_grams),
    )
