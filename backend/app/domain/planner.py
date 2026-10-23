"""Robust multi-period purchase scheduling.

Given cash flow (income, obligations, opening balance), a protected reserve and a
set of planned purchases, choose *when* to buy each item, or postpone it, so that
the balance never falls below the reserve in **any** protected scenario (e.g.
"salary on time" and "salary delayed two months"), while maximising the
priority-weighted value of what gets bought on time.

Formulation (solved exactly with OR-Tools CP-SAT; integers only)
------------------------------------------------------------------
Periods ``t = 0..T-1`` are the rest of this month, then calendar months. Buying
item ``i`` in period ``t`` means paying on a fixed day ``pay(i, t)``: its latest
on-time day if the target falls in ``t``, otherwise the period's *safe pay day*
(the day after which the period's lowest balance is highest, typically just after
salary lands).

Variables ``x[i,t] ∈ {0,1}``, ``Σ_t x[i,t] ≤ 1``.  For scenario ``s`` and day ``k``
let ``low[s,k]`` be the day's lowest no-purchase balance (outflows are applied
before inflows, as in the cash-flow engine) and ``R`` the reserve:

    Σ_{i,t : pay(i,t) ≤ k} cost_i · x[i,t]  ≤  max(low[s,k] - R, 0)

Spending only accumulates, so the constraint is needed only on *record-low* days
(lower than every later day); all others are implied. This keeps the model small
while remaining exact at day granularity.

Objective: maximise ``Σ value[i,t] · x[i,t]``: value encodes tier and priority,
and decays for buying late (soft or hard deadline) or needlessly early.

Hard-deadline *needs* that cannot fit above the reserve are then checked for plain
solvency (``R = 0``); if they fit they are proposed as USE_RESERVE, never silently.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum

from ortools.sat.python import cp_model

from app.domain.cashflow import (
    IncomeSpec,
    ObligationSpec,
    PlannedSpend,
    ReservePolicy,
    Scenario,
    project,
)
from app.domain.money import Money
from app.domain.recurrence import add_months

TIER_WEIGHT: dict[str, int] = {"need": 1000, "want": 400, "desire": 150}
MAX_ITEMS = 300
MAX_HORIZON_MONTHS = 24


class Action(StrEnum):
    BUY_NOW = "buy_now"
    SCHEDULE = "schedule"
    POSTPONE = "postpone"
    WAIT_PRICE = "wait_price"
    USE_RESERVE = "use_reserve"


class Reason(StrEnum):
    SAFE = "safe"
    ON_TARGET = "on_target"
    LATE = "late"
    ABOVE_MAX_PRICE = "above_max_price"
    NOT_AFFORDABLE = "not_affordable"
    OUTRANKED = "outranked"
    NEEDS_RESERVE = "needs_reserve"


@dataclass(frozen=True, slots=True)
class PlanItem:
    ref: str
    name: str
    tier: str  # need | want | desire
    priority: int  # 1..5
    unit_price: int  # minor units
    quantity: int
    deadline: str  # hard | soft | none
    target_date: date | None = None
    lead_time_days: int = 0
    max_price: int | None = None

    @property
    def cost(self) -> int:
        return self.unit_price * self.quantity

    @property
    def latest_pay(self) -> date | None:
        if self.target_date is None:
            return None
        return self.target_date - timedelta(days=self.lead_time_days)


@dataclass(frozen=True, slots=True)
class Period:
    index: int
    start: date
    end: date  # exclusive

    @property
    def label(self) -> str:
        return f"{self.start.year:04d}-{self.start.month:02d}"

    def contains(self, day: date) -> bool:
        return self.start <= day < self.end


@dataclass(frozen=True, slots=True)
class NamedScenario:
    name: str
    scenario: Scenario


@dataclass(frozen=True, slots=True)
class Decision:
    ref: str
    action: Action
    reason: Reason
    period: int | None = None
    pay_on: date | None = None
    late: bool = False
    shortfall: int | None = None  # extra headroom needed to fit (minor units)
    shortfall_scenario: str | None = None
    shortfall_on: date | None = None
    # For USE_RESERVE: the later date on which it would fit without touching the reserve.
    alternative_pay_on: date | None = None


@dataclass(frozen=True, slots=True)
class ScenarioOutcome:
    name: str
    min_balance: int
    min_balance_on: date
    reserve_breached_without_purchases: bool
    first_reserve_breach_on: date | None
    first_negative_on: date | None


@dataclass
class PlanResult:
    currency: str
    periods: list[Period]
    safe_days: list[date]
    reserve_required: int
    decisions: list[Decision]
    outcomes: list[ScenarioOutcome]
    solver_status: str
    solve_ms: int
    objective: int
    warnings: list[str] = field(default_factory=list)


def build_periods(today: date, months: int) -> list[Period]:
    """Rest of this month, then whole calendar months up to the one containing today + months.

    Matches the projection horizon (``today`` to ``today + months``), so both screens agree.
    """
    if not 1 <= months <= MAX_HORIZON_MONTHS:
        raise ValueError(f"Horizon must be 1-{MAX_HORIZON_MONTHS} months")
    last_day = add_months(today, months) - timedelta(days=1)
    periods: list[Period] = []
    start = today
    while start <= last_day:
        next_month = add_months(date(start.year, start.month, 1), 1, 1)
        periods.append(Period(len(periods), start, next_month))
        start = next_month
    return periods


def item_value(item: PlanItem, t: int, target: int | None) -> int:
    """Integer utility of buying ``item`` in period ``t`` (always > 0)."""
    weight = TIER_WEIGHT[item.tier] * item.priority
    if target is None:
        mult = max(10, 100 - 3 * t)
    elif t <= target:
        mult = 100 - min(20, target - t)  # mild cost of tying up cash early
    else:
        late = t - target
        if item.deadline == "hard":
            mult = max(5, 40 - 10 * late)
        elif item.deadline == "soft":
            mult = max(10, 100 - 15 * late)
        else:
            mult = max(10, 100 - 5 * late)
    return weight * mult


class _Ledger:
    """Daily low balances for one scenario, with no purchases."""

    def __init__(self, start: date, lows: list[int]) -> None:
        self.start = start
        self.lows = lows
        # Record-low days: strictly lower than every later day (scan from the right).
        records: list[int] = []
        running: int | None = None
        for k in range(len(lows) - 1, -1, -1):
            if running is None or lows[k] < running:
                records.append(k)
                running = lows[k]
        self.records = sorted(records)

    def day(self, k: int) -> date:
        return self.start + timedelta(days=k)

    def index(self, day: date) -> int:
        return (day - self.start).days


def _daily_lows(
    *,
    opening: Money,
    start: date,
    end: date,
    incomes: Sequence[IncomeSpec],
    obligations: Sequence[ObligationSpec],
    scenario: Scenario,
    reserve: ReservePolicy,
) -> tuple[_Ledger, int]:
    proj = project(
        opening_balance=opening,
        start=start,
        end=end,
        incomes=incomes,
        obligations=obligations,
        scenario=scenario,
        reserve=reserve,
    )
    days = (end - start).days + 1
    lows: list[int] = []
    balance = proj.opening_balance
    events = proj.events
    j = 0
    for k in range(days):
        day = start + timedelta(days=k)
        low = balance
        while j < len(events) and events[j].on == day:
            balance = events[j].balance_after
            low = min(low, balance)
            j += 1
        lows.append(low)
    return _Ledger(start, lows), proj.reserve_required


def _safe_days(periods: Sequence[Period], ledgers: Sequence[_Ledger]) -> list[date]:
    """Per period, the earliest day maximising the worst-case lowest balance until period end."""
    out: list[date] = []
    for p in periods:
        first, last = ledgers[0].index(p.start), ledgers[0].index(p.end) - 1
        best_k, best_v = first, None
        suffix = [min(lg.lows[last] for lg in ledgers)]
        for k in range(last - 1, first - 1, -1):
            suffix.append(min(suffix[-1], *(lg.lows[k] for lg in ledgers)))
        suffix.reverse()  # suffix[k - first] = worst low over [k, last]
        for k in range(first, last + 1):
            v = suffix[k - first]
            if best_v is None or v > best_v:
                best_k, best_v = k, v
        out.append(ledgers[0].day(best_k))
    return out


def _target_period(item: PlanItem, periods: Sequence[Period]) -> int | None:
    """Index of the period containing the latest pay date (len(periods) if beyond horizon)."""
    latest = item.latest_pay
    if latest is None:
        return None
    if latest < periods[0].start:
        return 0
    for p in periods:
        if p.contains(latest):
            return p.index
    return len(periods)


def pay_date(item: PlanItem, period: Period, safe_day: date) -> date:
    """Payment day if ``item`` is bought in ``period``."""
    latest = item.latest_pay
    if latest is not None and period.contains(latest):
        return latest
    return safe_day


def _is_late(item: PlanItem, pay_on: date) -> bool:
    latest = item.latest_pay
    return item.deadline != "none" and latest is not None and pay_on > latest


def plan_purchases(
    *,
    opening_balance: Money,
    today: date,
    horizon_months: int,
    items: Sequence[PlanItem],
    incomes: Sequence[IncomeSpec] = (),
    obligations: Sequence[ObligationSpec] = (),
    scenarios: Sequence[NamedScenario] = (),
    reserve: ReservePolicy | None = None,
    time_limit_s: float = 5.0,
) -> PlanResult:
    _validate(items, scenarios)
    started = time.perf_counter()
    reserve = reserve or ReservePolicy()
    named = list(scenarios) or [NamedScenario("As expected", Scenario())]
    planner = _Planner(
        opening=opening_balance,
        today=today,
        horizon_months=horizon_months,
        items=items,
        named=named,
        incomes=incomes,
        obligations=obligations,
        reserve=reserve,
    )
    status_name, objective = planner.solve_reserve_safe(time_limit_s)
    planner.place_hard_needs_on_time()
    decisions = planner.decide()
    outcomes = _outcomes(
        opening=opening_balance,
        start=today,
        end=planner.end,
        incomes=incomes,
        obligations=obligations,
        named=named,
        reserve=reserve,
        items=items,
        decisions=decisions,
        reserve_required=planner.reserve_required,
        ledgers=planner.ledgers,
    )
    return PlanResult(
        currency=opening_balance.currency,
        periods=planner.periods,
        safe_days=planner.safe,
        reserve_required=planner.reserve_required,
        decisions=[decisions[it.ref] for it in items],
        outcomes=outcomes,
        solver_status=status_name,
        solve_ms=round((time.perf_counter() - started) * 1000),
        objective=objective,
        warnings=planner.warnings(),
    )


def _validate(items: Sequence[PlanItem], scenarios: Sequence[NamedScenario]) -> None:
    if len(items) > MAX_ITEMS:
        raise ValueError(f"At most {MAX_ITEMS} items can be planned at once")
    if len({i.ref for i in items}) != len(items):
        raise ValueError("Item refs must be unique")
    for it in items:
        if it.tier not in TIER_WEIGHT or not 1 <= it.priority <= 5 or it.cost < 0:
            raise ValueError(f"Invalid item {it.ref!r}")
    if len({s.name for s in scenarios}) != len(scenarios):
        raise ValueError("Scenario names must be unique")


class _Planner:
    """Shared state for one planning run; each public method is one stage."""

    def __init__(
        self,
        *,
        opening: Money,
        today: date,
        horizon_months: int,
        items: Sequence[PlanItem],
        named: Sequence[NamedScenario],
        incomes: Sequence[IncomeSpec],
        obligations: Sequence[ObligationSpec],
        reserve: ReservePolicy,
    ) -> None:
        self.today = today
        self.named = named
        self.periods = build_periods(today, horizon_months)
        self.end = self.periods[-1].end - timedelta(days=1)
        self.ledgers: list[_Ledger] = []
        self.reserve_required = 0
        for ns in named:
            ledger, self.reserve_required = _daily_lows(
                opening=opening,
                start=today,
                end=self.end,
                incomes=incomes,
                obligations=obligations,
                scenario=ns.scenario,
                reserve=reserve,
            )
            self.ledgers.append(ledger)
        self.safe = _safe_days(self.periods, self.ledgers)
        self.targets = {it.ref: _target_period(it, self.periods) for it in items}
        self.pay: dict[tuple[str, int], int] = {
            (it.ref, p.index): self.ledgers[0].index(pay_date(it, p, self.safe[p.index]))
            for it in items
            for p in self.periods
        }
        self.waiting = [
            it for it in items if it.max_price is not None and it.unit_price > it.max_price
        ]
        waiting_refs = {it.ref for it in self.waiting}
        self.candidates = [it for it in items if it.ref not in waiting_refs]
        self.chosen: dict[str, int] = {}
        self.reserve_users: dict[str, date | None] = {}  # ref -> later reserve-safe date

    def warnings(self) -> list[str]:
        return [
            f"In '{ns.name}', your balance falls below the reserve even with no purchases."
            for ns, lg in zip(self.named, self.ledgers, strict=True)
            if min(lg.lows) < self.reserve_required
        ]

    def spent_by(self, day_index: int) -> int:
        return sum(
            it.cost
            for it in self.candidates
            if it.ref in self.chosen and self.pay[it.ref, self.chosen[it.ref]] <= day_index
        )

    # ---- Stage 1: CP-SAT, reserve protected in every scenario ----------------
    def solve_reserve_safe(self, time_limit_s: float) -> tuple[str, int]:
        if not self.candidates:
            return "optimal", 0
        model = cp_model.CpModel()
        x: dict[tuple[str, int], cp_model.IntVar] = {}
        for it in self.candidates:
            for p in self.periods:
                x[it.ref, p.index] = model.new_bool_var(f"x_{it.ref}_{p.index}")
            model.add_at_most_one(x[it.ref, p.index] for p in self.periods)

        for lg in self.ledgers:
            for k in lg.records:
                paid = [
                    it.cost * x[it.ref, p.index]
                    for it in self.candidates
                    if it.cost > 0
                    for p in self.periods
                    if self.pay[it.ref, p.index] <= k
                ]
                if paid:
                    model.add(sum(paid) <= max(lg.lows[k] - self.reserve_required, 0))

        model.maximize(
            sum(
                item_value(it, p.index, self.targets[it.ref]) * x[it.ref, p.index]
                for it in self.candidates
                for p in self.periods
            )
        )
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit_s
        solver.parameters.num_workers = 1  # deterministic results for identical inputs
        solver.parameters.random_seed = 0
        status = solver.solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):  # pragma: no cover
            raise RuntimeError(f"Planner failed: {solver.status_name(status)}")
        self.chosen = {
            it.ref: p.index
            for it in self.candidates
            for p in self.periods
            if solver.value(x[it.ref, p.index])
        }
        name = "optimal" if status == cp_model.OPTIMAL else "feasible"
        return name, int(solver.objective_value)

    # ---- Stage 2: hard-deadline needs, on time, even if that uses the reserve ------
    def place_hard_needs_on_time(self) -> None:
        """Offer the on-time option for hard-deadline needs Stage 1 left out or made late.

        Only plain solvency is required here; the user must approve using the reserve.
        """

        def late_or_missing(it: PlanItem) -> bool:
            if it.ref not in self.chosen:
                return True
            return _is_late(it, self.ledgers[0].day(self.pay[it.ref, self.chosen[it.ref]]))

        stage2 = sorted(
            (
                it
                for it in self.candidates
                if it.tier == "need" and it.deadline == "hard" and late_or_missing(it)
            ),
            key=lambda it: (-it.priority, it.cost, it.ref),
        )
        for it in stage2:
            q = min(self.targets[it.ref] or 0, len(self.periods) - 1)
            day = self.pay[it.ref, q]
            later = self.chosen.pop(it.ref, None)
            solvent = all(
                self.spent_by(k) + it.cost <= lg.lows[k]
                for lg in self.ledgers
                for k in range(day, len(lg.lows))
            )
            if solvent:
                self.chosen[it.ref] = q
                self.reserve_users[it.ref] = (
                    self.ledgers[0].day(self.pay[it.ref, later]) if later is not None else None
                )
            elif later is not None:
                self.chosen[it.ref] = later  # on time is not even solvent; keep the safe date

    # ---- Stage 3: one explained decision per item ------------------------------
    def decide(self) -> dict[str, Decision]:
        decisions = {
            it.ref: Decision(it.ref, Action.WAIT_PRICE, Reason.ABOVE_MAX_PRICE)
            for it in self.waiting
        }
        for it in self.candidates:
            decisions[it.ref] = (
                self._scheduled(it) if it.ref in self.chosen else self._postponed(it)
            )
        return decisions

    def _scheduled(self, it: PlanItem) -> Decision:
        t = self.chosen[it.ref]
        on = self.ledgers[0].day(self.pay[it.ref, t])
        late = _is_late(it, on)
        if it.ref in self.reserve_users:
            return Decision(
                it.ref,
                Action.USE_RESERVE,
                Reason.NEEDS_RESERVE,
                t,
                on,
                late,
                alternative_pay_on=self.reserve_users[it.ref],
            )
        action = Action.BUY_NOW if on == self.today else Action.SCHEDULE
        reason = Reason.LATE if late else Reason.ON_TARGET if it.target_date else Reason.SAFE
        return Decision(it.ref, action, reason, t, on, late)

    def _postponed(self, it: PlanItem) -> Decision:
        best = min(self.targets[it.ref] or 0, len(self.periods) - 1)
        day = self.pay[it.ref, best]
        gap, gap_s, gap_k = _shortfall(
            it.cost, day, self.ledgers, self.reserve_required, self.spent_by
        )
        alone, _, _ = _shortfall(it.cost, day, self.ledgers, self.reserve_required, _nothing_spent)
        return Decision(
            it.ref,
            Action.POSTPONE,
            Reason.NOT_AFFORDABLE if alone > 0 else Reason.OUTRANKED,
            shortfall=gap,
            shortfall_scenario=self.named[gap_s].name,
            shortfall_on=self.ledgers[0].day(gap_k),
        )


def _nothing_spent(_day: int) -> int:
    return 0


def _shortfall(
    cost: int,
    day: int,
    ledgers: Sequence[_Ledger],
    reserve_required: int,
    spent_by: Callable[[int], int],
) -> tuple[int, int, int]:
    """Smallest extra headroom needed to pay ``cost`` on ``day``: (amount, scenario, day)."""
    worst, ws, wk = 0, 0, day
    for s, lg in enumerate(ledgers):
        for k in lg.records:
            if k < day:
                continue
            need = spent_by(k) + cost - max(lg.lows[k] - reserve_required, 0)
            if need > worst:
                worst, ws, wk = need, s, k
    return worst, ws, wk


def _outcomes(
    *,
    opening: Money,
    start: date,
    end: date,
    incomes: Sequence[IncomeSpec],
    obligations: Sequence[ObligationSpec],
    named: Sequence[NamedScenario],
    reserve: ReservePolicy,
    items: Sequence[PlanItem],
    decisions: dict[str, Decision],
    reserve_required: int,
    ledgers: Sequence[_Ledger],
) -> list[ScenarioOutcome]:
    by_ref = {it.ref: it for it in items}
    spends = [
        PlannedSpend(
            d.ref, by_ref[d.ref].name, Money(by_ref[d.ref].cost, opening.currency), d.pay_on
        )
        for d in decisions.values()
        if d.pay_on is not None
    ]
    out: list[ScenarioOutcome] = []
    for ns, lg in zip(named, ledgers, strict=True):
        proj = project(
            opening_balance=opening, start=start, end=end, incomes=incomes,
            obligations=obligations, planned=spends, scenario=ns.scenario, reserve=reserve,
        )  # fmt: skip
        out.append(
            ScenarioOutcome(
                name=ns.name,
                min_balance=proj.min_balance,
                min_balance_on=proj.min_balance_on,
                reserve_breached_without_purchases=min(lg.lows) < reserve_required,
                first_reserve_breach_on=proj.first_reserve_breach_on,
                first_negative_on=proj.first_negative_on,
            )
        )
    return out
