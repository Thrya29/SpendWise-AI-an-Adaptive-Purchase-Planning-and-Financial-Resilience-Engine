"""Price-drop forecasts that answer the user's real question: will it get cheap enough in time?

Retail prices rarely drift smoothly: they sit still, then jump (sales, clearances, cuts).
So the forecast models **drop episodes** rather than daily returns:

1. A day's *reference* price is the highest price seen in the preceding ``REFERENCE_DAYS``
   days, a proxy for the "regular" price that sales are measured against.
2. The target is expressed as a depth below today's reference (``target / reference``).
3. A drop episode starts on a day the price reaches that depth below its own reference;
   consecutive qualifying days are one episode, so a long sale is not counted many times.
4. Episodes are treated as a Poisson process. The rate uses a Gamma prior of
   ``PRIOR_EPISODES`` episodes per ``PRIOR_DAYS`` days, so short histories stay humble:
   ``rate = (episodes + PRIOR_EPISODES) / (span_days + PRIOR_DAYS)``.
5. ``P(reach target within H days) = 1 - exp(-rate * H)``.

The prior constants were chosen on one synthetic seed and evaluated on a held-out seed
(``research/forecast_calibration.py``; results in ``docs/results/forecast-calibration.md``).
Too little history means no forecast, never a guess. Everything is deterministic.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from fractions import Fraction

MIN_OBSERVATIONS = 5
MIN_SPAN_DAYS = 14
MAX_HORIZON_DAYS = 365
REFERENCE_DAYS = 7
RANGE_DAYS = 90
PRIOR_EPISODES = 2.0
PRIOR_DAYS = 60.0


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True, slots=True)
class PricePoint:
    day: date
    amount: int  # minor units, > 0


@dataclass(frozen=True, slots=True)
class Forecast:
    current: int
    reference: int  # today's "regular" price (highest in the last REFERENCE_DAYS days)
    target: int
    horizon_days: int
    probability: float  # 0..1
    episodes: int  # past drops at least this deep
    confidence: Confidence
    observations: int
    span_days: int
    recent_low: int  # descriptive 10th / 50th / 90th percentile over the last RANGE_DAYS
    recent_median: int
    recent_high: int


@dataclass(frozen=True, slots=True)
class NoForecast:
    reason: str
    observations: int
    span_days: int


def daily_series(points: Sequence[PricePoint]) -> list[int]:
    """One price per calendar day: the last observation of the day, carried forward."""
    if not points:
        return []
    by_day: dict[date, int] = {}
    for p in sorted(points, key=lambda p: p.day):
        if p.amount <= 0:
            raise ValueError("Prices must be positive")
        by_day[p.day] = p.amount
    first, last = min(by_day), max(by_day)
    series: list[int] = []
    current = by_day[first]
    for k in range((last - first).days + 1):
        current = by_day.get(first + timedelta(days=k), current)
        series.append(current)
    return series


def _percentile(values: Sequence[int], q: float) -> int:
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo))


def _references(series: Sequence[int]) -> list[int]:
    return [max(series[max(0, d - REFERENCE_DAYS) : d + 1]) for d in range(len(series))]


def _runs_below(series: Sequence[int], refs: Sequence[int], depth: Fraction) -> int:
    episodes, inside = 0, False
    for price, ref in zip(series, refs, strict=True):
        hit = price <= depth * ref
        if hit and not inside:
            episodes += 1
        inside = hit
    return episodes


def count_episodes(series: Sequence[int], depth: Fraction | float) -> int:
    """Most separate dips that reached at least ``depth`` x the reference price (depth < 1).

    Runs at a shallow depth can merge two distinct deep dips (the price never recovered
    above the shallow threshold in between), so the count is the maximum over this depth
    and every deeper level that occurs. This keeps a shallower target never less likely.
    """
    refs = _references(series)
    depth = Fraction(depth)
    # The count only changes at observed price/reference ratios, so those exact levels suffice.
    # Fractions keep every comparison exact (floats can turn 1000 <= 1000/38700*38700 False).
    levels = {Fraction(p, r) for p, r in zip(series, refs, strict=True) if p <= depth * r}
    return max((_runs_below(series, refs, d) for d in levels | {depth}), default=0)


def hit_probability(
    points: Sequence[PricePoint], target: int, horizon_days: int
) -> Forecast | NoForecast:
    if target <= 0:
        raise ValueError("Target must be positive")
    if not 1 <= horizon_days <= MAX_HORIZON_DAYS:
        raise ValueError(f"Horizon must be 1-{MAX_HORIZON_DAYS} days")
    distinct_days = len({p.day for p in points})
    series = daily_series(points)
    span = max(len(series) - 1, 0)
    if distinct_days < MIN_OBSERVATIONS or span < MIN_SPAN_DAYS:
        return NoForecast(
            reason=(
                f"Not enough price history yet: {distinct_days} check(s) over {span} day(s). "
                f"A forecast needs at least {MIN_OBSERVATIONS} checks over {MIN_SPAN_DAYS} days."
            ),
            observations=distinct_days,
            span_days=span,
        )

    current = series[-1]
    reference = max(series[-REFERENCE_DAYS - 1 :])
    recent = series[-RANGE_DAYS - 1 :]
    if target >= current:
        probability, episodes = 1.0, 0
    else:
        episodes = count_episodes(series, Fraction(target, reference))
        rate = (episodes + PRIOR_EPISODES) / (span + PRIOR_DAYS)
        probability = min(0.99, max(0.01, 1 - math.exp(-rate * horizon_days)))

    confidence = (
        Confidence.HIGH
        if span >= 120 and distinct_days >= 30
        else Confidence.MEDIUM
        if span >= 45
        else Confidence.LOW
    )
    return Forecast(
        current=current,
        reference=reference,
        target=target,
        horizon_days=horizon_days,
        probability=round(probability, 4),
        episodes=episodes,
        confidence=confidence,
        observations=distinct_days,
        span_days=span,
        recent_low=_percentile(recent, 0.1),
        recent_median=_percentile(recent, 0.5),
        recent_high=_percentile(recent, 0.9),
    )
