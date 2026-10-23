"""Property-based invariants for the cash-flow engine."""

from datetime import date, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.cashflow import (
    IncomeShock,
    IncomeSpec,
    ObligationSpec,
    PlannedSpend,
    Scenario,
    ShockMode,
    project,
)
from app.domain.money import Money
from app.domain.recurrence import Frequency

START = date(2026, 1, 1)
END = date(2026, 12, 31)

amounts = st.integers(min_value=0, max_value=10_000_000)
days = st.integers(min_value=0, max_value=364).map(lambda d: START + timedelta(days=d))
freqs = st.sampled_from(list(Frequency))

incomes = st.lists(
    st.builds(
        lambda a, f, d, s: IncomeSpec("inc", Money(a, "INR"), f, d, subject_to_shocks=s),
        amounts,
        freqs,
        days,
        st.booleans(),
    ),
    max_size=4,
)
obligations = st.lists(
    st.builds(
        lambda a, f, d, e: ObligationSpec("ob", Money(a, "INR"), f, d, essential=e),
        amounts,
        freqs,
        days,
        st.booleans(),
    ),
    max_size=4,
)
planned = st.lists(
    st.builds(lambda a, d: PlannedSpend("p", "p", Money(a, "INR"), d), amounts, days), max_size=5
)


@settings(max_examples=150, deadline=None)
@given(st.integers(-1_000_000, 10_000_000), incomes, obligations, planned)
def test_conservation_of_money(opening: int, inc: list, obs: list, pl: list) -> None:
    p = project(
        opening_balance=Money(opening, "INR"),
        start=START,
        end=END,
        incomes=inc,
        obligations=obs,
        planned=pl,
    )
    assert p.closing_balance == opening + sum(e.amount for e in p.events)
    running = opening
    for e in p.events:
        running += e.amount
        assert e.balance_after == running
    assert p.min_balance == min([opening, *(e.balance_after for e in p.events)])
    assert p.months[-1].closing_balance == p.closing_balance
    assert [e.on for e in p.events] == sorted(e.on for e in p.events)


@settings(max_examples=100, deadline=None)
@given(st.integers(0, 10_000_000), incomes, obligations, st.integers(1, 6))
def test_income_shocks_never_increase_cash_at_any_point(
    opening: int, inc: list, obs: list, months: int
) -> None:
    base = project(
        opening_balance=Money(opening, "INR"), start=START, end=END, incomes=inc, obligations=obs
    )
    for mode in ShockMode:
        shocked = project(
            opening_balance=Money(opening, "INR"),
            start=START,
            end=END,
            incomes=inc,
            obligations=obs,
            scenario=Scenario(shock=IncomeShock(months, START, mode)),
        )
        assert shocked.min_balance <= base.min_balance
        assert shocked.closing_balance <= base.closing_balance
        for a, b in zip(shocked.months, base.months, strict=True):
            assert a.closing_balance <= b.closing_balance


@settings(max_examples=100, deadline=None)
@given(st.integers(0, 10_000_000), incomes, obligations, planned)
def test_adding_spend_never_improves_safety(opening: int, inc: list, obs: list, pl: list) -> None:
    without = project(
        opening_balance=Money(opening, "INR"), start=START, end=END, incomes=inc, obligations=obs
    )
    with_spend = project(
        opening_balance=Money(opening, "INR"),
        start=START,
        end=END,
        incomes=inc,
        obligations=obs,
        planned=pl,
    )
    assert with_spend.min_balance <= without.min_balance
    if without.first_reserve_breach_on is not None:
        assert with_spend.first_reserve_breach_on is not None
        assert with_spend.first_reserve_breach_on <= without.first_reserve_breach_on
