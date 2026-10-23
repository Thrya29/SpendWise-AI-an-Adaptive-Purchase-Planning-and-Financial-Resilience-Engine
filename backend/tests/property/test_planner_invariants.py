"""The planner must never schedule a purchase that breaks the reserve in a protected scenario."""

from datetime import date

from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.cashflow import IncomeShock, IncomeSpec, ObligationSpec, ReservePolicy, Scenario
from app.domain.money import Money
from app.domain.planner import Action, NamedScenario, PlanItem, plan_purchases
from app.domain.recurrence import Frequency

TODAY = date(2026, 3, 10)

items_st = st.lists(
    st.builds(
        PlanItem,
        ref=st.uuids().map(str),
        name=st.just("item"),
        tier=st.sampled_from(["need", "want", "desire"]),
        priority=st.integers(1, 5),
        unit_price=st.integers(0, 3_000_000),
        quantity=st.integers(1, 3),
        deadline=st.sampled_from(["hard", "soft", "none"]),
        target_date=st.one_of(st.none(), st.dates(date(2026, 3, 1), date(2027, 3, 1))),
        lead_time_days=st.integers(0, 30),
        max_price=st.one_of(st.none(), st.integers(0, 3_000_000)),
        group=st.sampled_from([None, None, "g1", "g2"]),
    ),
    max_size=8,
    unique_by=lambda i: i.ref,
)


@settings(max_examples=60, deadline=None)
@given(
    opening=st.integers(0, 20_000_000),
    salary=st.integers(1, 10_000_000),
    rent=st.integers(1, 5_000_000),
    shock_months=st.integers(0, 3),
    reserve_months=st.integers(0, 3),
    items=items_st,
)
def test_scheduled_purchases_never_breach_reserve(
    opening: int, salary: int, rent: int, shock_months: int, reserve_months: int, items: list
) -> None:
    scenarios = [NamedScenario("base", Scenario())]
    if shock_months:
        scenarios.append(
            NamedScenario("shock", Scenario(shock=IncomeShock(shock_months, date(2026, 4, 1))))
        )
    result = plan_purchases(
        opening_balance=Money(opening, "INR"),
        today=TODAY,
        horizon_months=6,
        items=items,
        incomes=[IncomeSpec("pay", Money(salary, "INR"), Frequency.MONTHLY, date(2026, 4, 1))],
        obligations=[
            ObligationSpec("rent", Money(rent, "INR"), Frequency.MONTHLY, date(2026, 4, 3))
        ],
        scenarios=scenarios,
        reserve=ReservePolicy(months_of_essentials=reserve_months),
        time_limit_s=10,
    )
    by_ref = {d.ref: d for d in result.decisions}
    assert set(by_ref) == {i.ref for i in items}
    uses_reserve = any(d.action is Action.USE_RESERVE for d in result.decisions)

    for outcome in result.outcomes:
        # Never insolvent because of the plan, unless the scenario is insolvent anyway.
        if outcome.first_negative_on is not None:
            assert outcome.reserve_breached_without_purchases
        if not uses_reserve and not outcome.reserve_breached_without_purchases:
            assert outcome.first_reserve_breach_on is None

    for it in items:
        d = by_ref[it.ref]
        if it.max_price is not None and it.unit_price > it.max_price:
            assert d.action is Action.WAIT_PRICE
        if d.action is Action.POSTPONE:
            assert d.shortfall is not None and d.shortfall > 0 and d.pay_on is None
        if d.action in (Action.BUY_NOW, Action.SCHEDULE, Action.USE_RESERVE):
            assert d.pay_on is not None and d.pay_on >= TODAY
        if d.action is Action.USE_RESERVE:
            assert it.tier == "need" and it.deadline == "hard"
        if d.action is Action.ALTERNATIVE:
            winner = by_ref[d.chosen_alternative]
            assert (
                winner.pay_on is not None
                and next(i for i in items if i.ref == d.chosen_alternative).group == it.group
            )

    buying = (Action.BUY_NOW, Action.SCHEDULE, Action.USE_RESERVE)
    for group in ("g1", "g2"):
        members = [i for i in items if i.group == group]
        assert sum(by_ref[i.ref].action in buying for i in members) <= 1
