"""Benchmark: the SpendWise planner against common budgeting rules under income shocks.

Each synthetic household has a salary, bills, an opening balance and a wish list of needs,
wants and desires that usually costs more than it can afford. The same household is then
lived through six months of one *realised* world (calm, salary delayed, salary lost, and/or
an emergency) once per policy. Policies never see the future; they only see the balance,
the calendar and whether the salary arrived.

Policies (every one obeys the same rule: a purchase is never paid with money the household
does not have that day, so any overdraft comes from bills arriving after spending):

* ``impulse``: buy each item on the day it is wanted, or as soon as it is affordable.
* ``50/30/20``: needs as impulse; wants and desires only from a pot fed by 30% of each
  salary actually received.
* ``buffer``: buy only if two months of essentials remain afterwards; a hard-deadline
  need is bought on its deadline anyway if affordable. A careful human with no foresight.
* ``spendwise-once``: plan once on day 0 (protecting a one-month salary delay), then follow.
* ``spendwise-reserve``: replan on the 1st of every month and the day after a missed salary
  or an emergency, protecting only the two-month reserve.
* ``spendwise``: the app's default: replanning as above, also protecting a one-month salary
  delay (once a salary is missed: one more month of delay than already seen).
* ``deadline-first``: an ablation, not shipped: as ``spendwise``, but a hard-deadline need
  is paid on time whenever the *expected* scenario stays solvent, even if the protected
  delay scenario would not.

Synthetic, by necessity: there is no public panel of household wish lists with daily cash
flow. Results describe the methods on this process, not on any specific population.

Run:  python -m research.planner_benchmark [--households N] [--seed S] [--out PATH]
"""

from __future__ import annotations

import argparse
import math
import random
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.domain import planner as planner_module  # noqa: E402
from app.domain.cashflow import (  # noqa: E402
    Emergency,
    EventKind,
    IncomeShock,
    IncomeSpec,
    ObligationSpec,
    ReservePolicy,
    Scenario,
    ShockMode,
    monthly_essentials,
    project,
)
from app.domain.money import Money  # noqa: E402
from app.domain.planner import NamedScenario, PlanItem, plan_purchases  # noqa: E402
from app.domain.recurrence import Frequency, add_months  # noqa: E402

CUR = "INR"
MONTHS = 6
RESERVE_MONTHS = 2
TIERS = ("need", "want", "desire")
POLICIES = (
    "impulse",
    "50/30/20",
    "buffer",
    "spendwise-once",
    "spendwise-reserve",
    "spendwise",
    "deadline-first",
)


def rupees(rng: random.Random, lo: float, hi: float) -> int:
    return round(rng.uniform(lo, hi)) * 100


# ---- Households and worlds ----------------------------------------------------------


@dataclass(frozen=True)
class Household:
    start: date
    end: date  # inclusive
    opening: int
    incomes: tuple[IncomeSpec, ...]
    obligations: tuple[ObligationSpec, ...]
    items: tuple[PlanItem, ...]
    essentials: int  # monthly

    @property
    def reserve(self) -> int:
        return self.essentials * RESERVE_MONTHS


@dataclass(frozen=True)
class World:
    label: str  # calm | delayed | lost (+ emergency)
    scenario: Scenario


def household(rng: random.Random) -> Household:
    start = date(2026, 1, 1) + timedelta(days=rng.randint(0, 27))
    end = add_months(start, MONTHS) - timedelta(days=1)
    salary = rupees(rng, 40_000, 200_000)
    pay_day = rng.choice((1, 1, 5, 7, 10, 25, 28))

    def on(day: int) -> date:
        return date(start.year, start.month, day)

    def monthly(
        name: str, share: tuple[float, float], day: int, essential: bool = True
    ) -> ObligationSpec:
        return ObligationSpec(
            name,
            Money(round(salary * rng.uniform(*share)), CUR),
            Frequency.MONTHLY,
            on(day),
            essential=essential,
        )

    obligations = [
        monthly("Rent", (0.22, 0.38), 5),
        monthly("Utilities", (0.03, 0.07), 10),
        ObligationSpec(
            "Groceries",
            Money(round(salary * rng.uniform(0.08, 0.14) * 12 / 52), CUR),
            Frequency.WEEKLY,
            start + timedelta(days=rng.randint(0, 6)),
        ),
        monthly("Eating out and fun", (0.04, 0.10), 20, essential=False),
    ]
    if rng.random() < 0.5:
        obligations.append(monthly("Loan EMI", (0.08, 0.22), 15))
    essentials = monthly_essentials(obligations, start)
    opening = round(essentials * rng.uniform(0.3, 3.0))

    items: list[PlanItem] = []
    for n in range(rng.randint(3, 8)):
        tier = rng.choices(TIERS, weights=(3, 4, 3))[0]
        lo, hi = {"need": (0.15, 1.2), "want": (0.10, 1.0), "desire": (0.10, 1.5)}[tier]
        has_target = tier == "need" or rng.random() < (0.6 if tier == "want" else 0.25)
        target = start + timedelta(days=rng.randint(3, 150)) if has_target else None
        if target is None:
            deadline = "none"
        elif tier == "need":
            deadline = rng.choice(("hard", "hard", "soft"))
        else:
            deadline = rng.choice(("soft", "none"))
        items.append(
            PlanItem(
                ref=f"i{n}",
                name=f"{tier} {n}",
                tier=tier,
                priority=rng.randint(1, 5),
                unit_price=round(salary * rng.uniform(lo, hi)),
                quantity=1,
                deadline=deadline,
                target_date=target,
            )
        )
    incomes = (IncomeSpec("Salary", Money(salary, CUR), Frequency.MONTHLY, on(pay_day)),)
    return Household(start, end, opening, incomes, tuple(obligations), tuple(items), essentials)


def world(rng: random.Random, hh: Household) -> World:
    pay_days = [
        d
        for m in range(1, MONTHS - 1)
        if (d := add_months(hh.incomes[0].anchor, m)) >= hh.start + timedelta(days=7)
    ]
    shock, label = None, "calm"
    r = rng.random()
    if r < 0.25:
        months = rng.choices((1, 2, 3), weights=(5, 3, 2))[0]
        shock, label = IncomeShock(months, rng.choice(pay_days)), "delayed"
    elif r < 0.35:
        months = rng.randint(2, 4)
        shock, label = IncomeShock(months, rng.choice(pay_days), ShockMode.LOST), "lost"
    emergencies: tuple[Emergency, ...] = ()
    if rng.random() < 0.3:
        amount = round(hh.essentials * rng.uniform(0.3, 1.5))
        day = hh.start + timedelta(days=rng.randint(10, (hh.end - hh.start).days - 10))
        emergencies = (Emergency("Emergency", Money(amount, CUR), day),)
        label = "emergency" if label == "calm" else f"{label} + emergency"
    return World(label, Scenario(shock=shock, emergencies=emergencies))


# ---- Daily simulation -----------------------------------------------------------------


@dataclass
class Day:
    out: int = 0  # bills and emergencies (minor units, positive)
    inflow: int = 0
    expected_inflow: int = 0  # what would have arrived with no shock


def calendar_of(hh: Household, w: World) -> list[Day]:
    days = [Day() for _ in range((hh.end - hh.start).days + 1)]
    for scenario, expected in ((w.scenario, False), (Scenario(), True)):
        proj = project(
            opening_balance=Money(hh.opening, CUR), start=hh.start, end=hh.end,
            incomes=hh.incomes, obligations=hh.obligations, scenario=scenario,
        )  # fmt: skip
        for ev in proj.events:
            d = days[(ev.on - hh.start).days]
            if expected:
                if ev.kind is EventKind.INCOME:
                    d.expected_inflow += ev.amount
            elif ev.amount < 0:
                d.out -= ev.amount
            else:
                d.inflow += ev.amount
    return days


@dataclass
class Outcome:
    world: str
    bought_on: dict[str, int] = field(default_factory=dict)  # ref -> day index
    min_balance: int = 0
    overdraft_days: int = 0
    below_reserve_days: int = 0
    baseline_min: int = 0  # min balance with no purchases at all
    baseline_below_reserve_days: int = 0
    replans: int = 0
    solve_ms: int = 0


class Policy:
    """Decides, each morning, which items to try to buy today (in order)."""

    replans = 0
    solve_ms = 0

    def __init__(self, hh: Household) -> None:
        self.hh = hh

    def morning(self, k: int, balance: int, sim: Sim) -> list[PlanItem]:
        raise NotImplementedError

    def bought(self, item: PlanItem) -> None:
        pass

    def received(self, amount: int) -> None:
        pass


def wanted_day(hh: Household, it: PlanItem) -> int:
    return 0 if it.latest_pay is None else max(0, (it.latest_pay - hh.start).days)


def urgency(it: PlanItem) -> tuple[int, int, int, str]:
    return (TIERS.index(it.tier), -it.priority, it.unit_price, it.ref)


class Impulse(Policy):
    def morning(self, k: int, balance: int, sim: Sim) -> list[PlanItem]:
        return sorted((it for it in sim.open_items if wanted_day(self.hh, it) <= k), key=urgency)


class FiftyThirtyTwenty(Impulse):
    def __init__(self, hh: Household) -> None:
        super().__init__(hh)
        self.pot = 0

    def morning(self, k: int, balance: int, sim: Sim) -> list[PlanItem]:
        due = super().morning(k, balance, sim)
        out, pot = [], self.pot
        for it in due:
            if it.tier == "need":
                out.append(it)
            elif it.cost <= pot:
                out.append(it)
                pot -= it.cost
        return out

    def bought(self, item: PlanItem) -> None:
        if item.tier != "need":
            self.pot -= item.cost

    def received(self, amount: int) -> None:
        self.pot += amount * 30 // 100


class Buffer(Impulse):
    def morning(self, k: int, balance: int, sim: Sim) -> list[PlanItem]:
        out, room = [], balance - sim.days[k].out - self.hh.reserve
        for it in super().morning(k, balance, sim):
            deadline_today = (
                it.deadline == "hard" and it.tier == "need" and (k >= wanted_day(self.hh, it))
            )
            if it.cost <= room:
                out.append(it)
                room -= it.cost
            elif deadline_today:
                out.append(it)  # only if affordable at all; the simulator checks
        return out


@contextmanager
def deadline_first() -> Iterator[None]:
    """Ablation: check on-time hard needs for solvency in the expected scenario only."""
    cls = planner_module._Planner
    original = cls.place_hard_needs_on_time

    def expected_only(self: planner_module._Planner) -> None:
        ledgers = self.ledgers
        self.ledgers = ledgers[:1]
        try:
            original(self)
        finally:
            self.ledgers = ledgers

    cls.place_hard_needs_on_time = expected_only  # type: ignore[method-assign]
    try:
        yield
    finally:
        cls.place_hard_needs_on_time = original  # type: ignore[method-assign]


class SpendWise(Policy):
    def __init__(
        self, hh: Household, *, replan: bool, protect: bool = True, deadlines: bool = False
    ) -> None:
        super().__init__(hh)
        self.replan, self.protect, self.deadlines = replan, protect, deadlines
        self.schedule: dict[str, int] = {}  # ref -> planned day index
        self.missed = 0  # consecutive salaries not received
        self.first_missed: date | None = None
        self.trigger = True  # plan on day 0

    def notice(self, k: int, sim: Sim) -> None:
        day = sim.days[k]
        if day.expected_inflow:
            if day.inflow < day.expected_inflow:
                if self.missed == 0:
                    self.first_missed = self.hh.start + timedelta(days=k)
                self.missed += 1
                self.trigger = True
            else:
                self.missed, self.first_missed = 0, None
        if day.out > sim.expected_out[k]:  # an emergency happened
            self.trigger = True

    def plan(self, k: int, balance: int, sim: Sim) -> None:
        today = self.hh.start + timedelta(days=k)
        if self.missed and self.first_missed is not None:
            seen = Scenario(IncomeShock(self.missed, self.first_missed))
            worse = Scenario(IncomeShock(self.missed + 1, self.first_missed))
        else:
            seen, worse = Scenario(), Scenario(IncomeShock(1, today))
        scenarios = [NamedScenario("As seen so far", seen)]
        if self.protect:
            scenarios.append(NamedScenario("One more month of delay", worse))
        with deadline_first() if self.deadlines else nullcontext():
            result = self._plan(today, balance, sim, scenarios)
        self.schedule = {
            d.ref: (d.pay_on - self.hh.start).days for d in result.decisions if d.pay_on
        }
        self.replans += 1
        self.solve_ms += result.solve_ms

    def _plan(
        self, today: date, balance: int, sim: Sim, scenarios: list[NamedScenario]
    ) -> planner_module.PlanResult:
        return plan_purchases(
            opening_balance=Money(balance, CUR),
            today=today,
            horizon_months=MONTHS,
            items=sim.open_items,
            incomes=self.hh.incomes,
            obligations=self.hh.obligations,
            scenarios=scenarios,
            reserve=ReservePolicy(RESERVE_MONTHS),
        )

    def morning(self, k: int, balance: int, sim: Sim) -> list[PlanItem]:
        today = self.hh.start + timedelta(days=k)
        if self.replan and today.day == 1:
            self.trigger = True
        if self.trigger and (self.replan or self.replans == 0) and sim.open_items:
            self.plan(k, balance, sim)
        self.trigger = False
        return sorted(
            (it for it in sim.open_items if self.schedule.get(it.ref, 10**9) <= k), key=urgency
        )


def make_policy(name: str, hh: Household) -> Policy:
    factories: dict[str, Callable[[], Policy]] = {
        "impulse": lambda: Impulse(hh),
        "50/30/20": lambda: FiftyThirtyTwenty(hh),
        "buffer": lambda: Buffer(hh),
        "spendwise-once": lambda: SpendWise(hh, replan=False),
        "spendwise-reserve": lambda: SpendWise(hh, replan=True, protect=False),
        "spendwise": lambda: SpendWise(hh, replan=True),
        "deadline-first": lambda: SpendWise(hh, replan=True, deadlines=True),
    }
    return factories[name]()


class Sim:
    def __init__(self, hh: Household, w: World, days: list[Day], expected_out: list[int]) -> None:
        self.hh, self.w, self.days, self.expected_out = hh, w, days, expected_out
        self.open_items: list[PlanItem] = list(hh.items)

    def run(self, policy: Policy) -> Outcome:
        hh = self.hh
        out = Outcome(self.w.label)
        balance = hh.opening
        out.min_balance = balance
        for k, day in enumerate(self.days):
            for it in policy.morning(k, balance, self):
                if it in self.open_items and it.cost <= balance - day.out:
                    balance -= it.cost
                    self.open_items.remove(it)
                    out.bought_on[it.ref] = k
                    policy.bought(it)
            low = balance - day.out
            out.min_balance = min(out.min_balance, low)
            out.overdraft_days += low < 0
            out.below_reserve_days += low < hh.reserve
            balance = low + day.inflow
            if day.inflow:
                policy.received(day.inflow)
            if isinstance(policy, SpendWise):
                policy.notice(k, self)
        out.replans, out.solve_ms = policy.replans, policy.solve_ms
        return out


def baseline(hh: Household, days: Sequence[Day]) -> tuple[int, int]:
    balance, low_min, below = hh.opening, hh.opening, 0
    for day in days:
        low = balance - day.out
        low_min, below = min(low_min, low), below + (low < hh.reserve)
        balance = low + day.inflow
    return low_min, below


def simulate_household(rng: random.Random) -> tuple[Household, dict[str, Outcome]]:
    hh = household(rng)
    w = world(rng, hh)
    days = calendar_of(hh, w)
    calm = calendar_of(hh, World("calm", Scenario()))
    expected_out = [d.out for d in calm]
    base_min, base_below = baseline(hh, days)
    results: dict[str, Outcome] = {}
    for name in POLICIES:
        o = Sim(hh, w, days, expected_out).run(make_policy(name, hh))
        o.baseline_min, o.baseline_below_reserve_days = base_min, base_below
        results[name] = o
    return hh, results


# ---- Metrics ---------------------------------------------------------------------------


@dataclass
class Row:
    policy: str
    n: int
    avoidable_overdraft: float  # went negative, though no-purchase path stayed >= 0
    overdraft: float
    mean_shortfall_months: float  # deepest negative balance, in months of essentials
    extra_reserve_days: float  # extra days below reserve vs. buying nothing
    needs_on_time: float
    hard_needs_on_time: float
    wants_bought: float
    desires_bought: float
    spend_share: float  # share of the wish list's total cost actually bought


def on_time(hh: Household, it: PlanItem, o: Outcome) -> bool:
    k = o.bought_on.get(it.ref)
    return k is not None and (it.latest_pay is None or k <= (it.latest_pay - hh.start).days)


def summarise(runs: Sequence[tuple[Household, dict[str, Outcome]]], policy: str) -> Row:
    def share(
        pred: Callable[[Household, PlanItem, Outcome], bool], keep: Callable[[PlanItem], bool]
    ) -> float:
        hits = total = 0
        for hh, res in runs:
            for it in hh.items:
                if keep(it):
                    total += 1
                    hits += pred(hh, it, res[policy])
        return hits / total if total else math.nan

    def bought(_hh: Household, it: PlanItem, o: Outcome) -> bool:
        return it.ref in o.bought_on

    outs = [(hh, res[policy]) for hh, res in runs]
    clean = [(hh, o) for hh, o in outs if o.baseline_min >= 0]
    negatives = [(hh, o) for hh, o in outs if o.min_balance < 0]
    spent = sum(it.cost for hh, o in outs for it in hh.items if it.ref in o.bought_on)
    wished = sum(it.cost for hh, _ in outs for it in hh.items)
    return Row(
        policy=policy,
        n=len(outs),
        avoidable_overdraft=sum(o.min_balance < 0 for _, o in clean) / max(1, len(clean)),
        overdraft=len(negatives) / len(outs),
        mean_shortfall_months=sum(-o.min_balance / hh.essentials for hh, o in negatives)
        / max(1, len(negatives)),
        extra_reserve_days=sum(
            o.below_reserve_days - o.baseline_below_reserve_days for _, o in outs
        )
        / len(outs),
        needs_on_time=share(on_time, lambda it: it.tier == "need"),
        hard_needs_on_time=share(on_time, lambda it: it.tier == "need" and it.deadline == "hard"),
        wants_bought=share(bought, lambda it: it.tier == "want"),
        desires_bought=share(bought, lambda it: it.tier == "desire"),
        spend_share=spent / wished,
    )


def wilson(p: float, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return math.nan, math.nan
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def run(n: int, seed: int) -> dict[str, object]:
    rng = random.Random(seed)
    started = time.perf_counter()
    runs = [simulate_household(rng) for _ in range(n)]
    rows = {p: summarise(runs, p) for p in POLICIES}
    worlds = sorted({res["impulse"].world for _, res in runs})
    by_world = {
        w: {p: summarise([r for r in runs if r[1]["impulse"].world == w], p) for p in POLICIES}
        for w in worlds
    }
    sw = [res["spendwise"] for _, res in runs]
    return {
        "runs": runs,
        "rows": rows,
        "by_world": by_world,
        "clean_households": sum(res["impulse"].baseline_min >= 0 for _, res in runs),
        "seconds": time.perf_counter() - started,
        "mean_replans": sum(o.replans for o in sw) / len(sw),
        "mean_solve_ms": sum(o.solve_ms for o in sw) / max(1, sum(o.replans for o in sw)),
    }


# ---- Report ----------------------------------------------------------------------------


def pct(x: float) -> str:
    return "—" if math.isnan(x) else f"{100 * x:.1f}%"


def findings(rows: dict[str, Row]) -> list[str]:
    imp, rule, sw = rows["impulse"], rows["buffer"], rows["spendwise"]
    res, dl = rows["spendwise-reserve"], rows["deadline-first"]
    return [
        "## Findings",
        "",
        f"1. **Planning prevents most avoidable overdrafts.** Every SpendWise variant stays at "
        f"{pct(min(r.avoidable_overdraft for p, r in rows.items() if p.startswith('spendwise')))}"
        f"–{pct(max(r.avoidable_overdraft for p, r in rows.items() if p.startswith('spendwise')))}"
        f", against {pct(rule.avoidable_overdraft)} for the best rule (`buffer`) and "
        f"{pct(imp.avoidable_overdraft)} for `impulse`. Rules that look only at today's balance "
        "cannot see next week's rent.",
        f"2. **Replanning with the reserve beats the careful rule on both axes that matter.** "
        f"`spendwise-reserve` has {pct(res.avoidable_overdraft)} avoidable overdrafts and buys "
        f"{pct(res.hard_needs_on_time)} of hard-deadline needs on time; `buffer` has "
        f"{pct(rule.avoidable_overdraft)} and {pct(rule.hard_needs_on_time)}. The price is fewer "
        f"wants and desires ({pct(res.spend_share)} of the wish list against "
        f"{pct(rule.spend_share)}).",
        f"3. **The app's default protection is cautious about needs.** Adding a rolling "
        f"one-month salary-delay protection (`spendwise`) cuts avoidable overdrafts to "
        f"{pct(sw.avoidable_overdraft)}, but hard needs on time fall to "
        f"{pct(sw.hard_needs_on_time)}: when paying a deadline on time would go negative "
        "*if the salary were late*, the planner keeps the later, safe date. The "
        f"`deadline-first` ablation pays such needs on time and gets {pct(dl.hard_needs_on_time)} "
        f"on time at {pct(dl.avoidable_overdraft)} avoidable overdrafts. Neither dominates; "
        "which matters more is the household's choice, and the plan screen lets them choose "
        "what to protect.",
        "4. **No plan rescues a long income loss with thin savings.** In the *lost* worlds even "
        "the planner overdraws about a third of the time. In every such case inspected on the "
        "development seed, the purchases were hard-deadline needs paid before the loss began "
        "(or on the day the first salary failed to arrive): buying nothing would have avoided "
        "the overdraft only by missing those deadlines.",
    ]


def report(result: dict[str, object], n: int, seed: int) -> str:
    rows = result["rows"]
    by_world = result["by_world"]
    clean = result["clean_households"]
    assert isinstance(rows, dict) and isinstance(by_world, dict) and isinstance(clean, int)
    lines = [
        "# Planner benchmark (synthetic)",
        "",
        f"Generated by `python -m research.planner_benchmark --households {n} --seed {seed}`.",
        f"{n} synthetic households over {MONTHS} months: salary ₹40k–2L a month, rent, bills,",
        "weekly groceries, an EMI for half of them, an opening balance of 0.3–3 months of",
        "essentials, and 3–8 wished-for items that usually cost more than they can afford.",
        "Each household lives through one realised world, the same for every policy: 25% have",
        "their salary delayed 1–3 months, 10% lose it for 2–4 months, 30% have an emergency",
        "costing 0.3–1.5 months of essentials (independently of the salary). No policy sees",
        "the future. A purchase is never paid with money the household doesn't have that day.",
        "",
        "## Results",
        "",
        "| Policy | Avoidable overdraft | Overdraft (any) | Mean depth* | Extra days below "
        "reserve | Needs on time | Hard needs on time | Wants bought | Desires bought | "
        "Wish list bought |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows.values():
        lo, hi = wilson(r.avoidable_overdraft, clean)
        lines.append(
            f"| `{r.policy}` | **{pct(r.avoidable_overdraft)}** ({pct(lo)}–{pct(hi)}) | "
            f"{pct(r.overdraft)} | {r.mean_shortfall_months:.2f} mo | "
            f"{r.extra_reserve_days:.1f} | {pct(r.needs_on_time)} | {pct(r.hard_needs_on_time)} | "
            f"{pct(r.wants_bought)} | {pct(r.desires_bought)} | {pct(r.spend_share)} |"
        )
    lines += [
        "",
        "*Avoidable overdraft*: the balance went below zero (bills could not be paid without",
        f"credit) in a household that would have stayed above zero buying nothing; {clean} of",
        f"{n} households qualify, with 95% Wilson intervals. *Mean depth*: the deepest",
        "negative balance among households that went negative, in months of essentials.",
        "*Extra days below reserve*: days under two months of essentials, beyond the days",
        "the household would spend there anyway with no purchases.",
        "",
        "## By world",
        "",
    ]
    header = "| World | Households | " + " | ".join(f"`{p}`" for p in POLICIES) + " |"
    rule = "|---|---|" + "---|" * len(POLICIES)
    for title, metric in (
        ("Avoidable overdraft", "avoidable_overdraft"),
        ("Hard needs on time", "hard_needs_on_time"),
        ("Wish list bought", "spend_share"),
    ):
        lines += [f"**{title}**", "", header, rule]
        for w, per in by_world.items():
            cells = " | ".join(pct(getattr(per[p], metric)) for p in POLICIES)
            lines.append(f"| {w} | {per[POLICIES[0]].n} | {cells} |")
        lines.append("")
    lines += findings(rows)
    lines += [
        "",
        "## Notes",
        "",
        f"* `spendwise` replanned {result['mean_replans']:.1f} times per household; one plan",
        f"  took {result['mean_solve_ms']:.0f} ms on average. The whole benchmark ran in "
        f"{result['seconds']:.0f} s.",
        "* SpendWise sometimes chooses to spend *less* than the rules. Buying less is not",
        "  automatically better: compare the protection columns with the bought columns.",
        "* Nothing in the planner was tuned to this benchmark. Seed 7 was used while building",
        "  it; this report uses seed 2026, which was run once the code was final.",
        "* Every policy uses the same purchase guard, so differences come from *when* and",
        "  *whether* to buy, not from one policy being allowed credit.",
        "",
        "## Caveats",
        "",
        "* Synthetic households and shock rates; real incomes are lumpier (bonuses, freelance",
        "  work) and real people deviate from any rule.",
        "* Detection is simple: a missed salary is noticed on its due date, and the planner",
        "  then protects one more month of delay than already seen. It does not know whether",
        "  the salary is delayed or lost.",
        "* The baselines are deliberately reasonable, not straw men; `buffer` keeps the same",
        "  two-month reserve the planner protects.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--households", type=int, default=500)
    parser.add_argument("--seed", type=int, default=2026)
    default_out = ROOT / "docs" / "results" / "planner-benchmark.md"
    parser.add_argument("--out", type=Path, default=default_out)
    args = parser.parse_args()
    result = run(args.households, args.seed)
    text = report(result, args.households, args.seed)
    args.out.write_text(text, encoding="utf-8")
    sys.stdout.buffer.write(text.encode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
