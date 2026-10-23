# ADR 0005: Robust purchase scheduling with CP-SAT

**Status:** Accepted · 2026-10-23

## Context
Users plan several purchases against uncertain income. Evaluating items one at a time ("can I
afford this?") misses the interaction between them: buying the headphones can make the laptop
unaffordable next month. The planner must choose a **portfolio and a schedule** together, and stay
safe under the shocks the user wants to guard against (late or lost salary, emergencies).

## Decision
**Model.** For each item *i* and period *t* (the rest of this month, then calendar months up to
`today + horizon`), a boolean variable `x[i,t]` means "buy *i* in *t*", with `Σ_t x[i,t] ≤ 1`.
Buying in *t* pays on a fixed day `pay(i,t)`:
* the item's latest on-time day (target date − lead time) if that falls in *t*;
* otherwise the period's **safe pay day**: the earliest day that maximises the worst-case lowest
  balance until period end. This is typically the day after salary lands, because the cash-flow
  engine conservatively applies outflows before inflows on the same day.

**Constraints, exact at day granularity.** For every protected scenario *s* and day *k*:
`Σ_{i,t: pay(i,t) ≤ k} cost_i · x[i,t] ≤ max(low[s,k] − reserve, 0)`, where `low` is the day's
lowest no-purchase balance from the tested cash-flow engine. Spending only accumulates, so only
*record-low* days (lower than every later day) need a constraint. All others are implied, which
keeps the model small (a few dozen constraints per scenario).

**Objective.** Maximise `Σ value(i,t) · x[i,t]`:
`value = tier weight (need 1000, want 400, desire 150) × priority (1–5) × timing multiplier`.
The timing multiplier is 100% on target, 1%/month cheaper per month bought early (cash tied up),
15%/month less for a late soft deadline, and a large drop for a late hard deadline. All integers.

**Stage 2: consent for the reserve.** A hard-deadline *need* that cannot be bought on time above
the reserve is re-checked for plain solvency (`reserve = 0`). If it fits, it is proposed as
`use_reserve` together with the later reserve-safe date, if one exists. Applying without
`allow_reserve` uses that safe date, so dipping into the reserve always requires explicit approval.

**Explainability.** Postponed items report the exact extra headroom needed, the date it is needed
by, and the scenario that binds. They are also marked *outranked* when they would fit on their
own but lose to higher-value items.

**Determinism.** Single-worker CP-SAT with a fixed seed: identical inputs give identical plans.

## Alternatives considered
* **Greedy by priority:** simple, but provably suboptimal when a cheaper lower-priority item and a
  costly higher-priority one compete for the same headroom. It is kept as a Phase 6 benchmark
  baseline.
* **Monthly-bucket constraints:** smaller, but pinning payments to the 1st of the month made the
  solver avoid months whose salary also lands on the 1st. Replaced by the day-exact formulation.
* **MILP (CBC/HiGHS):** comparable for this size. CP-SAT gives exact integer arithmetic (money in
  minor units), robust performance on boolean scheduling, and is well maintained.

## Consequences
* A property-based test (1,000 random cases run during development, 60 in CI) checks that
  re-projecting any plan never breaches the reserve in a protected scenario, unless the scenario
  breaches it with no purchases at all, or the user explicitly approved reserve use.
* Plans are saved as drafts with a fingerprint of every row version they depend on. Applying a
  plan after any data change, or on a later day, is refused (409) and the user re-plans. This is
  the model-predictive "re-plan on every change" loop.
* Postponed items are re-planned by default, so a salary that recovers brings them back.
