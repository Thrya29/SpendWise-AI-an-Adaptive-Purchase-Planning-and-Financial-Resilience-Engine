from datetime import date
from decimal import Decimal

import pytest

from app.domain.cashflow import (
    Emergency,
    EventKind,
    IncomeShock,
    IncomeSpec,
    ObligationSpec,
    PlannedSpend,
    ReservePolicy,
    Scenario,
    ShockMode,
    monthly_equivalent,
    project,
)
from app.domain.money import Money
from app.domain.recurrence import Frequency


def inr(rupees: int) -> Money:
    return Money(rupees * 100, "INR")


SALARY = IncomeSpec("Salary", inr(45_000), Frequency.MONTHLY, date(2026, 11, 1))
RENT = ObligationSpec("Essentials", inr(20_000), Frequency.MONTHLY, date(2026, 11, 5))
START, END = date(2026, 10, 25), date(2027, 1, 31)


def test_reference_scenario_salary_delayed_two_months_with_emergency() -> None:
    """Savings 60k, essentials 20k/month, salary 45k delayed 2 months, 10k emergency."""
    scenario = Scenario(
        shock=IncomeShock(months=2, starts_on=date(2026, 11, 1), mode=ShockMode.DELAYED),
        emergencies=(Emergency("Medical", inr(10_000), date(2026, 10, 28)),),
    )
    p = project(
        opening_balance=inr(60_000),
        start=START,
        end=END,
        incomes=[SALARY],
        obligations=[RENT],
        scenario=scenario,
        reserve=ReservePolicy(months_of_essentials=2),
    )
    assert p.monthly_essentials == inr(20_000).amount_minor
    assert p.reserve_required == inr(40_000).amount_minor
    assert p.runway_months == Decimal("3.0")
    # 60k - 10k = 50k; -20k (Nov 5) = 30k  -> reserve breached
    assert p.first_reserve_breach_on == date(2026, 11, 5)
    # Dec 5: 10k is the lowest point; never negative
    assert p.min_balance == inr(10_000).amount_minor
    assert p.min_balance_on == date(2026, 12, 5)
    assert p.first_negative_on is None
    # Jan 1 receives the delayed Nov salary + Jan salary; Dec salary lands Feb 1 (outside horizon)
    jan_income = [e for e in p.events if e.kind is EventKind.INCOME]
    assert [(e.on, e.amount) for e in jan_income] == [
        (date(2027, 1, 1), inr(45_000).amount_minor),
        (date(2027, 1, 1), inr(45_000).amount_minor),
    ]
    assert p.closing_balance == inr(80_000).amount_minor
    assert not p.is_safe


def test_planned_purchase_check_flags_insolvency() -> None:
    scenario = Scenario(shock=IncomeShock(2, date(2026, 11, 1)))
    p = project(
        opening_balance=inr(60_000),
        start=START,
        end=END,
        incomes=[SALARY],
        obligations=[RENT],
        planned=[PlannedSpend("laptop", "Laptop", inr(30_000), date(2026, 11, 10))],
        scenario=scenario,
    )
    (check,) = p.planned_checks
    assert check.ref == "laptop"
    assert check.balance_after == inr(10_000).amount_minor
    assert not check.keeps_reserve and check.stays_solvent
    assert p.first_negative_on == date(2026, 12, 5)


def test_no_shock_is_safe_and_month_summaries_complete() -> None:
    p = project(
        opening_balance=inr(60_000), start=START, end=END, incomes=[SALARY], obligations=[RENT]
    )
    assert p.is_safe
    assert [m.month for m in p.months] == ["2026-10", "2026-11", "2026-12", "2027-01"]
    oct_, nov = p.months[0], p.months[1]
    assert oct_.closing_balance == inr(60_000).amount_minor and oct_.inflow == 0
    assert nov.inflow == inr(45_000).amount_minor
    assert nov.essential_outflow == inr(20_000).amount_minor
    assert nov.closing_balance == inr(85_000).amount_minor


def test_lost_income_never_arrives() -> None:
    p = project(
        opening_balance=inr(60_000),
        start=START,
        end=END,
        incomes=[SALARY],
        obligations=[RENT],
        scenario=Scenario(shock=IncomeShock(2, date(2026, 11, 1), ShockMode.LOST)),
    )
    incomes = [e.on for e in p.events if e.kind is EventKind.INCOME]
    assert incomes == [date(2027, 1, 1)]


def test_shock_ignores_streams_not_subject_to_shocks() -> None:
    rent_income = IncomeSpec(
        "Rental income", inr(5_000), Frequency.MONTHLY, date(2026, 11, 1), subject_to_shocks=False
    )
    p = project(
        opening_balance=inr(0),
        start=START,
        end=END,
        incomes=[rent_income],
        scenario=Scenario(shock=IncomeShock(2, date(2026, 11, 1), ShockMode.LOST)),
    )
    assert len([e for e in p.events if e.kind is EventKind.INCOME]) == 3


def test_outflows_before_inflows_same_day() -> None:
    inc = IncomeSpec("Pay", inr(100), Frequency.ONCE, date(2026, 11, 1))
    ob = ObligationSpec("Bill", inr(100), Frequency.ONCE, date(2026, 11, 1))
    p = project(opening_balance=inr(0), start=START, end=END, incomes=[inc], obligations=[ob])
    assert [e.kind for e in p.events] == [EventKind.OBLIGATION, EventKind.INCOME]
    assert p.first_negative_on == date(2026, 11, 1)


def test_discretionary_obligations_and_buffer() -> None:
    gym = ObligationSpec("Gym", inr(1_000), Frequency.MONTHLY, date(2026, 11, 3), essential=False)
    p = project(
        opening_balance=inr(10_000),
        start=START,
        end=END,
        obligations=[RENT, gym],
        reserve=ReservePolicy(months_of_essentials=0, min_buffer=inr(500).amount_minor),
    )
    assert p.monthly_essentials == inr(20_000).amount_minor
    assert p.reserve_required == inr(500).amount_minor
    assert p.months[1].discretionary_outflow == inr(1_000).amount_minor


def test_monthly_equivalents() -> None:
    assert monthly_equivalent(1200, Frequency.YEARLY) == 100
    assert monthly_equivalent(300, Frequency.QUARTERLY) == 100
    assert monthly_equivalent(1200, Frequency.WEEKLY) == 5200
    assert monthly_equivalent(999, Frequency.ONCE) == 0


def test_runway_none_without_essentials_and_validation() -> None:
    p = project(opening_balance=inr(1), start=START, end=END)
    assert p.runway_months is None
    with pytest.raises(ValueError, match="before start"):
        project(opening_balance=inr(1), start=END, end=START)
    with pytest.raises(ValueError, match="5 years"):
        project(opening_balance=inr(1), start=START, end=date(2032, 1, 1))
    with pytest.raises(ValueError, match="Convert amounts"):
        project(
            opening_balance=inr(1),
            start=START,
            end=END,
            obligations=[ObligationSpec("x", Money(1, "USD"), Frequency.ONCE, START)],
        )
    with pytest.raises(ValueError):
        IncomeShock(25, START)
    with pytest.raises(ValueError):
        ReservePolicy(months_of_essentials=-1)
    with pytest.raises(ValueError):
        ReservePolicy(min_buffer=-1)
