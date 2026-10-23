# ADR 0007: Price-drop forecasting by drop episodes

**Status:** Accepted · 2026-10-23

## Context
Users wait for a better price when an item is above their limit. The question they need answered
is **"what is the chance it gets this cheap before I need it?"**, not a single predicted price.
Any number shown must be honest: calibrated, withheld when evidence is thin, and never presented
as a guarantee.

## Decision
`app/domain/forecast.py`, pure and deterministic:

1. Build a daily series from the item's own price checks (last of the day, carried forward).
2. The **reference** (regular) price on each day is the highest price over the previous 7 days.
3. Express the target as a depth below today's reference.
4. Count **drop episodes**: separate occasions the price fell to at least that depth below its
   reference. A multi-day sale counts once. The count is the maximum over this depth and every
   deeper observed level, with exact `Fraction` comparisons, so a shallower target is never
   rated less likely.
5. Model episodes as a Poisson process with a Gamma prior of 2 episodes per 60 days:
   `rate = (episodes + 2) / (span_days + 60)` and `P = 1 − exp(−rate × H)`.
6. **No forecast** below 5 checks or 14 days of history. Confidence is high at 120+ days and 30+
   checks, medium at 45+ days, otherwise low.
7. The "recent range" is descriptive only (10th, 50th and 90th percentile over 90 days), never
   presented as a prediction.

## Evidence
`research/forecast_calibration.py` simulates retail histories (sticky prices, sales, cuts,
irregular checks) and scores 3,000 forecasts. Priors were grid-searched on seed 7, and results
are reported on **held-out seed 11** ([results](../results/forecast-calibration.md)):

| | Rejected v1 | Adopted |
|---|---|---|
| Brier skill vs. climatology given the true base rate | −0.108 | **+0.227** |
| Expected calibration error | 0.196 | **0.030** |

A CI test re-runs a smaller study and fails if the skill drops below 0.12 or the calibration
error rises above 0.07.

## Alternatives considered
* **Overlapping H-day windows plus a random-walk fallback (v1).** Rejected after measurement:
  overlapping windows over a few sales overstated the evidence, and a continuous random walk
  fits sticky, jumping retail prices poorly.
* **Point forecasts, ARIMA or ML regressors.** These answer the wrong question and need far more
  history than a personal price-check log provides.

## Consequences
* The planner's *wait for a better price* decisions show the chance of reaching the limit before
  the item is needed. If buying a lower-ranked alternative now would rule out a preferred item
  that is waiting, the plan says so.
* Results are on synthetic data. They must be re-measured on real price histories before
  accuracy is claimed for any particular shop.
