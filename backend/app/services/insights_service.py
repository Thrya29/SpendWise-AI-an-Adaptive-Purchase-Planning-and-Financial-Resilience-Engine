"""Savings insights built on the same cash-flow engine as planning."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.cashflow import IncomeShock, ReservePolicy, Scenario, ShockMode, project
from app.domain.recurrence import add_months
from app.models.entities import User
from app.services.ledger import load_planning_inputs


@dataclass(frozen=True, slots=True)
class SafeToLock:
    currency: str
    amount: int  # can be locked away for ``months`` without breaking plans or the reserve
    months: int
    available_now: int
    reserve: int
    monthly_essentials: int
    runway_months: str | None
    binding_scenario: str
    lowest_point_on: date
    warnings: list[str]


async def safe_to_lock(
    session: AsyncSession, user: User, today: date, *, months: int, protect_delay_months: int
) -> SafeToLock:
    """Largest amount that could sit in a deposit for ``months`` with every plan still safe.

    Locking money lowers the balance by the same amount every day until maturity, so the
    answer is the lowest (balance - reserve) over the horizon, across protected scenarios,
    with all scheduled purchases included.
    """
    inputs = await load_planning_inputs(session, user, today, include_planned=True)
    reserve = ReservePolicy(user.reserve_months, user.reserve_buffer_minor)
    end = add_months(today, months)
    scenarios = [("As expected", Scenario())]
    if protect_delay_months > 0:
        unit = "month" if protect_delay_months == 1 else "months"
        scenarios.append(
            (
                f"Salary delayed {protect_delay_months} {unit}",
                Scenario(shock=IncomeShock(protect_delay_months, today, ShockMode.DELAYED)),
            )
        )
    best: tuple[int, str, date] | None = None
    projection = None
    for name, scenario in scenarios:
        projection = project(
            opening_balance=inputs.opening_balance, start=today, end=end,
            incomes=inputs.incomes, obligations=inputs.obligations, planned=inputs.planned,
            scenario=scenario, reserve=reserve,
        )  # fmt: skip
        headroom = projection.min_balance - projection.reserve_required
        if best is None or headroom < best[0]:
            best = (headroom, name, projection.min_balance_on)
    assert best is not None and projection is not None
    return SafeToLock(
        currency=inputs.currency,
        amount=max(0, best[0]),
        months=months,
        available_now=inputs.opening_balance.amount_minor,
        reserve=projection.reserve_required,
        monthly_essentials=projection.monthly_essentials,
        runway_months=str(projection.runway_months) if projection.runway_months else None,
        binding_scenario=best[1],
        lowest_point_on=best[2],
        warnings=inputs.warnings,
    )
