from datetime import date, timedelta

import pytest

from app.domain.cashflow import (
    Emergency,
    IncomeShock,
    IncomeSpec,
    ObligationSpec,
    ReservePolicy,
    Scenario,
)
from app.domain.money import Money
from app.domain.planner import (
    Action,
    NamedScenario,
    PlanItem,
    Reason,
    build_periods,
    item_value,
    pay_date,
    plan_purchases,
)
from app.domain.recurrence import Frequency

TODAY = date(2026, 10, 25)


def inr(rupees: int) -> Money:
    return Money(rupees * 100, "INR")


SALARY = IncomeSpec("Salary", inr(45_000), Frequency.MONTHLY, date(2026, 11, 1))
RENT = ObligationSpec("Essentials", inr(20_000), Frequency.MONTHLY, date(2026, 11, 5))
DELAYED_2 = NamedScenario(
    "Salary delayed 2 months", Scenario(shock=IncomeShock(2, date(2026, 11, 1)))
)
BASE = NamedScenario("As expected", Scenario())


def item(ref: str, rupees: int, tier: str = "want", priority: int = 3, **kw: object) -> PlanItem:
    defaults: dict[str, object] = {"quantity": 1, "deadline": "soft"}
    defaults.update(kw)
    return PlanItem(ref, ref, tier, priority, rupees * 100, **defaults)  # type: ignore[arg-type]


def run(
    items: list[PlanItem], scenarios=(BASE,), opening: int = 60_000, months: int = 6,
    today: date = TODAY, **kw,
):  # fmt: skip
    return plan_purchases(
        opening_balance=inr(opening), today=today, horizon_months=months, items=items,
        incomes=[SALARY], obligations=[RENT], scenarios=scenarios,
        reserve=ReservePolicy(months_of_essentials=2), **kw,
    )  # fmt: skip


def by_ref(result):
    return {d.ref: d for d in result.decisions}


def test_periods_cover_rest_of_month_then_calendar_months() -> None:
    ps = build_periods(TODAY, 3)
    assert [(p.start, p.end) for p in ps] == [
        (date(2026, 10, 25), date(2026, 11, 1)),
        (date(2026, 11, 1), date(2026, 12, 1)),
        (date(2026, 12, 1), date(2027, 1, 1)),
        (date(2027, 1, 1), date(2027, 2, 1)),  # today + 3 months = 25 Jan, so January counts
    ]
    assert ps[1].label == "2026-11"
    on_first = build_periods(date(2026, 11, 1), 3)
    assert [p.label for p in on_first] == ["2026-11", "2026-12", "2027-01"]
    with pytest.raises(ValueError):
        build_periods(TODAY, 0)


def test_affordable_item_without_date_is_bought_now() -> None:
    r = run([item("headphones", 5_000)])
    d = by_ref(r)["headphones"]
    assert d.action is Action.BUY_NOW and d.pay_on == TODAY and d.reason is Reason.SAFE
    assert r.reserve_required == inr(40_000).amount_minor
    assert r.solver_status == "optimal"


def test_waits_until_target_month_instead_of_buying_early() -> None:
    r = run([item("trip", 10_000, target_date=date(2027, 2, 20), lead_time_days=10)])
    d = by_ref(r)["trip"]
    assert d.action is Action.SCHEDULE and d.pay_on == date(2027, 2, 10)
    assert d.reason is Reason.ON_TARGET and not d.late


def test_salary_delay_scenario_forces_postponement_and_reports_shortfall() -> None:
    laptop = item("laptop", 30_000, tier="need", priority=5, target_date=date(2026, 11, 20))
    safe = by_ref(run([laptop]))["laptop"]
    assert safe.action is Action.SCHEDULE  # fine when salary arrives

    r = run([laptop], scenarios=(BASE, DELAYED_2))
    d = by_ref(r)["laptop"]
    # Delayed: 60k -> 40k (Nov 5) -> 20k (Dec 5); both salaries land Jan 1. Headroom above the
    # 40k reserve is 0 in Nov and negative in Dec, so the earliest safe month is January.
    assert (d.action, d.period, d.late, d.reason) == (Action.SCHEDULE, 3, True, Reason.LATE)
    assert d.pay_on == date(2027, 1, 2)  # safe day: just after the delayed salaries land
    # With salary delayed, ₹60k - 20k - 20k = 20k < 40k reserve before any purchase.
    assert any("below the reserve even with no purchases" in w for w in r.warnings)


def test_needs_outrank_desires_when_cash_is_tight() -> None:
    # Planning October only (salary and rent start in November): 60k - 40k reserve = 20k.
    r = run(
        [
            item("rent-deposit", 15_000, tier="need", priority=4),
            item("concert", 15_000, tier="desire", priority=5),
        ],
        months=1,
        today=date(2026, 10, 1),
    )
    d = by_ref(r)
    assert d["rent-deposit"].action is Action.BUY_NOW
    assert d["concert"].action is Action.POSTPONE
    assert d["concert"].reason is Reason.OUTRANKED
    assert d["concert"].shortfall == inr(10_000).amount_minor


def test_unaffordable_item_reports_not_affordable_with_exact_shortfall() -> None:
    r = run([item("car", 500_000)], months=2)
    d = by_ref(r)["car"]
    assert d.action is Action.POSTPONE and d.reason is Reason.NOT_AFFORDABLE
    # Best headroom is period 0: 60k - 40k = 20k -> need 480k more.
    assert d.shortfall == inr(480_000).amount_minor
    assert d.shortfall_scenario == "As expected"


def test_price_ceiling_means_wait_for_price() -> None:
    r = run([item("phone", 50_000, max_price=40_000 * 100)])
    d = by_ref(r)["phone"]
    assert d.action is Action.WAIT_PRICE and d.reason is Reason.ABOVE_MAX_PRICE


def test_hard_need_uses_reserve_only_when_explicitly_flagged() -> None:
    # Needs 35k by 2026-10-30; headroom is only 20k, but solvency allows it.
    med = item("surgery", 35_000, tier="need", priority=5, deadline="hard",
               target_date=date(2026, 10, 30))  # fmt: skip
    r = run([med], months=2)
    d = by_ref(r)["surgery"]
    assert d.action is Action.USE_RESERVE and d.reason is Reason.NEEDS_RESERVE
    assert d.pay_on == date(2026, 10, 30)
    # The user is also told the reserve-safe alternative: just after salary lands.
    assert d.alternative_pay_on == date(2026, 11, 2)
    base = r.outcomes[0]
    assert base.first_reserve_breach_on == date(2026, 10, 30)
    assert base.first_negative_on is None


def test_hard_need_that_is_not_even_solvent_on_time_stays_late() -> None:
    big = item("repair", 70_000, tier="need", priority=5, deadline="hard",
               target_date=date(2026, 10, 30))  # fmt: skip
    d = by_ref(run([big], months=3))["repair"]
    assert d.action is Action.SCHEDULE and d.late and d.alternative_pay_on is None


def test_hard_deadline_missed_is_marked_late() -> None:
    gift = item("gift", 25_000, tier="want", priority=5, deadline="hard",
                target_date=date(2026, 10, 28))  # fmt: skip
    d = by_ref(run([gift], months=3))["gift"]
    assert d.action is Action.SCHEDULE and d.late and d.reason is Reason.LATE


def test_plan_respects_reserve_in_every_protected_scenario() -> None:
    items = [item(f"i{k}", 6_000 + 1_000 * k, tier=t, priority=1 + k % 5)
             for k, t in enumerate(["need", "want", "desire"] * 4)]  # fmt: skip
    shock = NamedScenario("Delay 1", Scenario(shock=IncomeShock(1, date(2026, 12, 1))))
    r = run(items, scenarios=(BASE, shock), opening=120_000)
    for o in r.outcomes:
        assert o.first_reserve_breach_on is None and o.first_negative_on is None


def test_emergency_scenario_and_determinism() -> None:
    em = NamedScenario("Emergency", Scenario(emergencies=(Emergency("x", inr(15_000), TODAY),)))
    items = [item("a", 8_000), item("b", 8_000), item("c", 8_000)]
    r1, r2 = run(items, scenarios=(BASE, em)), run(items, scenarios=(BASE, em))
    assert [d.ref for d in r1.decisions if d.action is Action.BUY_NOW] == [
        d.ref for d in r2.decisions if d.action is Action.BUY_NOW
    ]
    # 20k headroom minus 15k emergency -> only 5k this month: nothing bought now.
    assert not [d for d in r1.decisions if d.action is Action.BUY_NOW]


def test_value_function_shape() -> None:
    it = item("x", 1, tier="need", priority=5, deadline="soft")
    assert item_value(it, 3, 3) > item_value(it, 0, 3) > 0  # prefer on-target over early
    assert item_value(it, 3, 3) > item_value(it, 4, 3)  # prefer on-target over late
    hard = item("h", 1, tier="need", priority=5, deadline="hard")
    assert item_value(hard, 4, 3) < item_value(it, 4, 3)  # hard deadlines decay faster
    no_date = item("n", 1)
    assert item_value(no_date, 0, None) > item_value(no_date, 5, None)
    assert item_value(item("w", 1, tier="want"), 0, None) < item_value(
        item("n2", 1, tier="need"), 0, None
    )


def test_pay_date_uses_target_inside_period_else_safe_day() -> None:
    p = build_periods(TODAY, 3)
    safe = date(2026, 11, 2)
    it = item("x", 1, target_date=date(2026, 12, 20), lead_time_days=5)
    assert pay_date(it, p[2], date(2026, 12, 2)) == date(2026, 12, 15)
    assert pay_date(it, p[1], safe) == safe  # buying early: on the period's safe day
    assert pay_date(item("y", 1), p[1], safe) == safe


def test_safe_day_is_after_salary_not_before() -> None:
    r = run([item("x", 1_000, target_date=date(2026, 12, 25), deadline="none")], months=3)
    # Salary lands on the 1st, but outflows-first means paying on the 1st dips first.
    assert r.safe_days == [TODAY, date(2026, 11, 2), date(2026, 12, 2), date(2027, 1, 2)]


def test_input_validation() -> None:
    with pytest.raises(ValueError, match="unique"):
        run([item("a", 1), item("a", 2)])
    with pytest.raises(ValueError, match="Invalid item"):
        run([item("a", 1, tier="luxury")])
    with pytest.raises(ValueError, match="Scenario names"):
        run([item("a", 1)], scenarios=(BASE, BASE))
    assert run([]).decisions == []


def test_alternatives_group_buys_at_most_one_and_prefers_the_better_fit() -> None:
    # 20k headroom this month: either laptop fits alone, never both.
    pro = item("laptop-pro", 18_000, tier="need", priority=5, group="laptop")
    air = item("laptop-air", 12_000, tier="need", priority=4, group="laptop")
    solo = item("mouse", 1_000)
    r = run([pro, air, solo], months=1, today=date(2026, 10, 1))
    d = by_ref(r)
    bought = [k for k in ("laptop-pro", "laptop-air") if d[k].action is Action.BUY_NOW]
    assert bought == ["laptop-pro"]  # higher priority wins within the group
    assert d["laptop-air"].action is Action.ALTERNATIVE
    assert d["laptop-air"].chosen_alternative == "laptop-pro"
    assert d["mouse"].action is Action.BUY_NOW


def test_group_with_one_affordable_member_and_ungrouped_items_unaffected() -> None:
    big = item("tv-oled", 90_000, tier="want", priority=5, group="tv")
    small = item("tv-led", 15_000, tier="want", priority=3, group="tv")
    d = by_ref(run([big, small], months=1, today=date(2026, 10, 1)))
    assert d["tv-led"].action is Action.BUY_NOW and d["tv-oled"].action is Action.ALTERNATIVE
    lonely = item("solo", 1_000, group="only-member")
    assert by_ref(run([lonely]))["solo"].action is Action.BUY_NOW


def test_hard_need_on_time_only_if_salary_arrives_is_offered_not_chosen() -> None:
    # 35k due 30 Oct. On time it is fine if salary lands (25k -> 70k on 1 Nov), but with the
    # salary 2 months late: 25k -> 5k (5 Nov) -> -15k (5 Dec). The safe date stands; paying on
    # time is offered with the scenario it would break and the exact shortfall.
    fees = item("fees", 35_000, tier="need", priority=5, deadline="hard",
                target_date=date(2026, 10, 30))  # fmt: skip
    d = by_ref(run([fees], scenarios=(BASE, DELAYED_2), months=4))["fees"]
    assert d.action is not Action.USE_RESERVE and d.pay_on != date(2026, 10, 30)
    assert d.on_time is not None
    assert d.on_time.pay_on == date(2026, 10, 30)
    assert d.on_time.at_risk == ("Salary delayed 2 months",)
    assert (d.on_time.shortfall, d.on_time.shortfall_on) == (15_000_00, date(2026, 12, 5))


def test_no_on_time_option_when_it_is_safe_or_impossible() -> None:
    med = item("surgery", 35_000, tier="need", priority=5, deadline="hard",
               target_date=date(2026, 10, 30))  # fmt: skip
    assert by_ref(run([med], months=2))["surgery"].on_time is None  # plain USE_RESERVE
    big = item("repair", 70_000, tier="need", priority=5, deadline="hard",
               target_date=date(2026, 10, 30))  # fmt: skip
    # Not solvent even as expected: nothing to offer.
    assert by_ref(run([big], scenarios=(BASE, DELAYED_2), months=3))["repair"].on_time is None


def test_running_out_of_time_schedules_nothing_instead_of_failing(monkeypatch) -> None:
    from ortools.sat.python import cp_model  # noqa: PLC0415

    class NoAnswer(cp_model.CpSolver):
        def solve(self, *_args, **_kw):  # type: ignore[override]
            return cp_model.UNKNOWN

    monkeypatch.setattr(cp_model, "CpSolver", NoAnswer)
    laptop = item("laptop", 10_000, tier="need", priority=5)
    r = run([laptop])
    assert r.solver_status == "timeout" and r.objective == 0
    assert r.decisions[0].action is Action.POSTPONE
    assert any("ran out of time" in w for w in r.warnings)


def test_a_tiny_time_limit_still_returns_a_safe_plan() -> None:
    items = [item(f"i{n}", 5_000 + n * 700, priority=1 + n % 5) for n in range(40)]
    r = run(items, scenarios=(BASE, DELAYED_2), time_limit_s=0.001)
    assert r.solver_status in {"optimal", "feasible", "timeout"}
    assert all(o.first_reserve_breach_on is None for o in r.outcomes if o.name == "As expected")


def test_greedy_starting_plan_respects_every_reserve_cap() -> None:
    import random  # noqa: PLC0415
    from bisect import bisect_left  # noqa: PLC0415

    from app.domain.planner import _Planner  # noqa: PLC0415

    for seed in range(25):
        rng = random.Random(seed)
        items = [
            item(f"i{n}", rng.randint(1_000, 40_000), tier=rng.choice(["need", "want", "desire"]),
                 priority=rng.randint(1, 5), group=f"g{n % 4}" if n % 3 == 0 else None,
                 target_date=date(2026, 11, 1) + timedelta(days=rng.randint(0, 150))
                 if rng.random() < 0.6 else None)
            for n in range(rng.randint(3, 25))
        ]  # fmt: skip
        planner = _Planner(
            opening=inr(rng.randint(20_000, 200_000)), today=TODAY, horizon_months=6,
            items=items, named=[BASE, DELAYED_2], incomes=[SALARY], obligations=[RENT],
            reserve=ReservePolicy(months_of_essentials=2),
        )  # fmt: skip
        days, caps = planner._pay_days_and_caps()
        plan = planner._greedy_plan(days, caps)
        totals = [0] * len(days)
        for ref, t in plan.items():
            cost = next(it.cost for it in items if it.ref == ref)
            for i in range(bisect_left(days, planner.pay[ref, t]), len(days)):
                totals[i] += cost
        assert all(cap is None or total <= cap for total, cap in zip(totals, caps, strict=True))
        chosen_groups = [it.group for it in items if it.ref in plan and it.group]
        assert len(chosen_groups) == len(set(chosen_groups))
