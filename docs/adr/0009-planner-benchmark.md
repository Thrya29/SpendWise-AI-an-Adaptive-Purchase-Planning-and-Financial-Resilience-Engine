# ADR 0009: Benchmark the planner, keep the cautious default

**Status:** Accepted · 2026-10-26

## Context
The planner claims to keep households safe when salary is late or an emergency hits. That claim
needed a test against what people actually do: buy when they can, follow 50/30/20, or keep a
buffer. No public dataset joins wish lists with daily cash flow, so the test is a simulation.

## Decision
* A reproducible benchmark (`research/planner_benchmark.py`) of three budgeting rules and three
  ways of using the planner on 500 synthetic households, each living one realised world. Policies see only the past. The same purchase guard
  applies to all, so differences come from *when* and *whether* to buy.
* The headline metric is **avoidable overdraft**: the balance went negative although buying
  nothing would have kept it positive. Delivery is measured too (needs on time, wish list bought),
  so a policy cannot win by buying nothing.
* Development used seed 7. The report uses seed 2026, run once the code was final. Nothing in the
  planner was changed to suit the benchmark.
* The default protection stays as it is (one-month salary delay, re-applied at every replan),
  although the benchmark shows it costs hard deadlines: 32.9% on time against 67.6% with the
  reserve alone, for 3.8% against 9.0% avoidable overdrafts. A `deadline-first` variant (pay a
  hard need on time if the expected case stays solvent) reached 67.8% at 7.3%. It is kept as an
  ablation, not shipped, because it would sometimes knowingly risk rent for a deadline without the
  user's consent.

## Consequences
* The README states the trade-off, and users can turn delay protection off in the planner.
* Amendment (2026-10-26): instead of choosing for the user, each affected hard-deadline need now
  carries an explicit on-time option with the scenarios it would break and the exact shortfall.
  The user can opt in per item ("Pay on time anyway"). The default decision is unchanged, so the
  benchmark numbers still describe the default.
* A 24-household run in CI guards the ranking of overdraft rates.
* If real usage data accumulates (with consent), the benchmark should be repeated on it before any
  accuracy claim about real households.
