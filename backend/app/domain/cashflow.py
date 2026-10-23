"""Deterministic cash-flow projection under income shocks and emergencies.

Pure functions only: no I/O, no framework imports. Every figure the UI shows
about balances, runway and reserve safety comes from here, never from an LLM.

Conventions
-----------
* All amounts are integer minor units in a single base currency.
* Within a single day, outflows are applied before inflows (conservative).
* A salary *delay* moves affected payments later by N months; a salary *loss*
  removes them. Either can be applied only to income streams marked as
  ``subject_to_shocks``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from typing import NamedTuple

from app.domain.money import Money
from app.domain.recurrence import Frequency, add_months, occurrences


class EventKind(StrEnum):
    INCOME = "income"
    OBLIGATION = "obligation"
    PLANNED = "planned"
    EMERGENCY = "emergency"


class ShockMode(StrEnum):
    DELAYED = "delayed"
    LOST = "lost"


@dataclass(frozen=True, slots=True)
class IncomeSpec:
    name: str
    amount: Money
    frequency: Frequency
    anchor: date
    until: date | None = None
    subject_to_shocks: bool = True


@dataclass(frozen=True, slots=True)
class ObligationSpec:
    name: str
    amount: Money
    frequency: Frequency
    anchor: date
    until: date | None = None
    essential: bool = True


@dataclass(frozen=True, slots=True)
class PlannedSpend:
    ref: str
    name: str
    amount: Money
    on: date


@dataclass(frozen=True, slots=True)
class Emergency:
    name: str
    amount: Money
    on: date


@dataclass(frozen=True, slots=True)
class IncomeShock:
    months: int
    starts_on: date
    mode: ShockMode = ShockMode.DELAYED

    def __post_init__(self) -> None:
        if not 0 <= self.months <= 24:
            raise ValueError("Income shock must be between 0 and 24 months")


@dataclass(frozen=True, slots=True)
class ReservePolicy:
    months_of_essentials: int = 2
    min_buffer: int = 0  # minor units, on top of the essentials reserve

    def __post_init__(self) -> None:
        if not 0 <= self.months_of_essentials <= 24:
            raise ValueError("Reserve months must be between 0 and 24")
        if self.min_buffer < 0:
            raise ValueError("Minimum buffer cannot be negative")


@dataclass(frozen=True, slots=True)
class Scenario:
    shock: IncomeShock | None = None
    emergencies: tuple[Emergency, ...] = ()


@dataclass(frozen=True, slots=True)
class CashEvent:
    on: date
    kind: EventKind
    label: str
    amount: int  # signed minor units: + inflow, - outflow
    balance_after: int
    ref: str | None = None


@dataclass(frozen=True, slots=True)
class MonthSummary:
    month: str  # YYYY-MM
    inflow: int
    essential_outflow: int
    discretionary_outflow: int
    planned_outflow: int
    emergency_outflow: int
    closing_balance: int
    min_balance: int


@dataclass(frozen=True, slots=True)
class PlannedCheck:
    ref: str
    name: str
    on: date
    amount: int
    balance_after: int
    keeps_reserve: bool
    stays_solvent: bool


@dataclass(frozen=True, slots=True)
class Projection:
    currency: str
    start: date
    end: date
    opening_balance: int
    closing_balance: int
    monthly_essentials: int
    reserve_required: int
    min_balance: int
    min_balance_on: date
    first_reserve_breach_on: date | None
    first_negative_on: date | None
    runway_months: Decimal | None
    events: list[CashEvent] = field(default_factory=list)
    months: list[MonthSummary] = field(default_factory=list)
    planned_checks: list[PlannedCheck] = field(default_factory=list)

    @property
    def is_safe(self) -> bool:
        return self.first_reserve_breach_on is None and self.first_negative_on is None


_MONTHLY_FACTOR: dict[Frequency, tuple[int, int]] = {
    Frequency.WEEKLY: (52, 12),
    Frequency.MONTHLY: (1, 1),
    Frequency.QUARTERLY: (1, 3),
    Frequency.YEARLY: (1, 12),
}


def _round_div(numerator: int, denominator: int) -> int:
    return int((Decimal(numerator) / Decimal(denominator)).quantize(Decimal(1), ROUND_HALF_EVEN))


def monthly_equivalent(amount: int, frequency: Frequency) -> int:
    """Normalise a recurring amount to an average monthly figure (one-offs contribute 0)."""
    if frequency is Frequency.ONCE:
        return 0
    mul, div = _MONTHLY_FACTOR[frequency]
    return _round_div(amount * mul, div)


def monthly_essentials(obligations: Sequence[ObligationSpec], as_of: date) -> int:
    total = 0
    for ob in obligations:
        if ob.essential and (ob.until is None or ob.until >= as_of):
            total += monthly_equivalent(ob.amount.amount_minor, ob.frequency)
    return total


def _shift_income(day: date, shock: IncomeShock | None) -> date | None:
    """Return the effective receipt date for an income occurrence, or None if lost."""
    if shock is None or shock.months == 0:
        return day
    window_end = add_months(shock.starts_on, shock.months)
    if not shock.starts_on <= day < window_end:
        return day
    if shock.mode is ShockMode.LOST:
        return None
    return add_months(day, shock.months)


def _ensure_currency(currency: str, *amounts: Money) -> None:
    for amount in amounts:
        if amount.currency != currency:
            raise ValueError(
                f"All projection inputs must be in {currency}; got {amount.currency}. "
                "Convert amounts before projecting."
            )


class _RawEvent(NamedTuple):
    on: date
    order: int  # 0 = outflow, 1 = inflow -> outflows are applied first within a day
    kind: EventKind
    label: str
    amount: int
    ref: str | None
    essential: bool


def _collect_events(
    *,
    start: date,
    end: date,
    incomes: Sequence[IncomeSpec],
    obligations: Sequence[ObligationSpec],
    planned: Sequence[PlannedSpend],
    scenario: Scenario,
) -> list[_RawEvent]:
    raw: list[_RawEvent] = []
    for inc in incomes:
        shock = scenario.shock if inc.subject_to_shocks else None
        # Delayed payments from before the horizon may land inside it; look back to catch them.
        lookback_start = add_months(start, -24) if shock is not None else start
        for day in occurrences(inc.frequency, inc.anchor, lookback_start, end, inc.until):
            effective = _shift_income(day, shock)
            if effective is not None and start <= effective <= end:
                raw.append(
                    _RawEvent(
                        effective,
                        1,
                        EventKind.INCOME,
                        inc.name,
                        inc.amount.amount_minor,
                        None,
                        False,
                    )
                )
    for ob in obligations:
        raw.extend(
            _RawEvent(
                day, 0, EventKind.OBLIGATION, ob.name, -ob.amount.amount_minor, None, ob.essential
            )
            for day in occurrences(ob.frequency, ob.anchor, start, end, ob.until)
        )
    raw.extend(
        _RawEvent(p.on, 0, EventKind.PLANNED, p.name, -p.amount.amount_minor, p.ref, False)
        for p in planned
        if start <= p.on <= end
    )
    raw.extend(
        _RawEvent(em.on, 0, EventKind.EMERGENCY, em.name, -em.amount.amount_minor, None, True)
        for em in scenario.emergencies
        if start <= em.on <= end
    )
    raw.sort(key=lambda r: (r.on, r.order, r.kind.value, r.label))
    return raw


def _month_summaries(
    months: dict[str, dict[str, int]], start: date, end: date, opening: int
) -> list[MonthSummary]:
    """One summary per calendar month in the horizon, carrying balances through quiet months."""
    summaries: list[MonthSummary] = []
    cursor = date(start.year, start.month, 1)
    carried = opening
    while cursor <= end:
        key = f"{cursor.year:04d}-{cursor.month:02d}"
        data = months.get(key)
        if data is None:
            summaries.append(MonthSummary(key, 0, 0, 0, 0, 0, carried, carried))
        else:
            carried = data["closing"]
            summaries.append(
                MonthSummary(
                    key,
                    data["inflow"],
                    data["essential"],
                    data["discretionary"],
                    data["planned"],
                    data["emergency"],
                    data["closing"],
                    data["min"],
                )
            )
        cursor = add_months(cursor, 1, 1)
    return summaries


def project(
    *,
    opening_balance: Money,
    start: date,
    end: date,
    incomes: Sequence[IncomeSpec] = (),
    obligations: Sequence[ObligationSpec] = (),
    planned: Sequence[PlannedSpend] = (),
    scenario: Scenario | None = None,
    reserve: ReservePolicy | None = None,
) -> Projection:
    if end < start:
        raise ValueError("Projection end must not be before start")
    if (end - start).days > 366 * 5:
        raise ValueError("Projection horizon is limited to 5 years")

    scenario = scenario or Scenario()
    reserve = reserve or ReservePolicy()
    currency = opening_balance.currency
    _ensure_currency(
        currency,
        *(i.amount for i in incomes),
        *(o.amount for o in obligations),
        *(p.amount for p in planned),
        *(e.amount for e in scenario.emergencies),
    )

    raw = _collect_events(
        start=start,
        end=end,
        incomes=incomes,
        obligations=obligations,
        planned=planned,
        scenario=scenario,
    )

    essentials = monthly_essentials(obligations, start)
    reserve_required = essentials * reserve.months_of_essentials + reserve.min_buffer

    balance = opening_balance.amount_minor
    min_balance, min_on = balance, start
    first_breach: date | None = start if balance < reserve_required else None
    first_negative: date | None = start if balance < 0 else None
    events: list[CashEvent] = []
    checks: list[PlannedCheck] = []
    months: dict[str, dict[str, int]] = {}

    def bucket(day: date) -> dict[str, int]:
        key = f"{day.year:04d}-{day.month:02d}"
        if key not in months:
            months[key] = {
                "inflow": 0,
                "essential": 0,
                "discretionary": 0,
                "planned": 0,
                "emergency": 0,
                "closing": balance,
                "min": balance,
            }
        return months[key]

    bucket(start)
    for day, _order, kind, label, amount, ref, essential in raw:
        b = bucket(day)
        balance += amount
        events.append(CashEvent(day, kind, label, amount, balance, ref))
        if kind is EventKind.INCOME:
            b["inflow"] += amount
        elif kind is EventKind.OBLIGATION:
            b["essential" if essential else "discretionary"] += -amount
        elif kind is EventKind.PLANNED:
            b["planned"] += -amount
            checks.append(
                PlannedCheck(
                    ref=ref or "",
                    name=label,
                    on=day,
                    amount=-amount,
                    balance_after=balance,
                    keeps_reserve=balance >= reserve_required,
                    stays_solvent=balance >= 0,
                )
            )
        else:
            b["emergency"] += -amount
        b["closing"] = balance
        b["min"] = min(b["min"], balance)
        if balance < min_balance:
            min_balance, min_on = balance, day
        if first_breach is None and balance < reserve_required:
            first_breach = day
        if first_negative is None and balance < 0:
            first_negative = day

    summaries = _month_summaries(months, start, end, opening_balance.amount_minor)

    runway = None
    if essentials > 0:
        runway = (Decimal(max(opening_balance.amount_minor, 0)) / Decimal(essentials)).quantize(
            Decimal("0.1"), ROUND_HALF_EVEN
        )

    return Projection(
        currency=currency,
        start=start,
        end=end,
        opening_balance=opening_balance.amount_minor,
        closing_balance=balance,
        monthly_essentials=essentials,
        reserve_required=reserve_required,
        min_balance=min_balance,
        min_balance_on=min_on,
        first_reserve_breach_on=first_breach,
        first_negative_on=first_negative,
        runway_months=runway,
        events=events,
        months=summaries,
        planned_checks=checks,
    )
