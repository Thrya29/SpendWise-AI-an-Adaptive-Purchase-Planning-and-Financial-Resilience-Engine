"""Educational investment maths: historical fund statistics and outcome simulations.

Nothing here recommends a security. Statistics describe the past; simulations show a
*range* of possible outcomes under stated assumptions, never a promised return.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import pairwise
from statistics import pstdev

TRADING_DAYS = 252
MAX_PATHS = 5_000
MAX_MONTHS = 480


@dataclass(frozen=True, slots=True)
class NavPoint:
    day: date
    nav: float  # NAVs are published with 4 decimals; statistics, not money, are computed


@dataclass(frozen=True, slots=True)
class FundStats:
    first_day: date
    last_day: date
    points: int
    cagr: dict[int, float]  # years -> annualised return over the trailing window
    volatility: float | None  # annualised standard deviation of daily log returns
    max_drawdown: float  # worst peak-to-trough fall, as a positive fraction


def fund_stats(series: Sequence[NavPoint]) -> FundStats | None:
    pts = sorted((p for p in series if p.nav > 0), key=lambda p: p.day)
    if len(pts) < 30:
        return None
    last = pts[-1]
    cagr: dict[int, float] = {}
    for years in (1, 3, 5):
        start_day = last.day - timedelta(days=round(365.25 * years))
        start = next((p for p in pts if p.day >= start_day), None)
        if start is None or (start.day - start_day).days > 10:
            continue  # not enough history for this window
        span = (last.day - start.day).days / 365.25
        if span > 0.9 * years:
            cagr[years] = (last.nav / start.nav) ** (1 / span) - 1
    recent = [p for p in pts if p.day >= last.day - timedelta(days=366)]
    returns = [math.log(b.nav / a.nav) for a, b in pairwise(recent)]
    volatility = pstdev(returns) * math.sqrt(TRADING_DAYS) if len(returns) >= 20 else None
    peak, worst = pts[0].nav, 0.0
    for p in pts:
        peak = max(peak, p.nav)
        worst = max(worst, 1 - p.nav / peak)
    return FundStats(pts[0].day, last.day, len(pts), cagr, volatility, worst)


@dataclass(frozen=True, slots=True)
class Simulation:
    months: int
    invested: int  # minor units contributed in total
    p10: int
    p50: int
    p90: int
    probability_of_loss: float  # final value below the amount invested
    median_max_drawdown: float  # typical worst fall from a peak along the way
    paths: int
    seed: int


def simulate(
    *,
    initial: int,
    monthly: int,
    months: int,
    annual_return: float,
    annual_volatility: float,
    paths: int = 2_000,
    seed: int = 42,
) -> Simulation:
    """Monte Carlo of a lump sum plus a monthly SIP under lognormal monthly returns.

    ``annual_return`` is the expected arithmetic annual return (e.g. 0.10); volatility is
    annualised. Contributions are made at the start of each month.
    """
    if initial < 0 or monthly < 0 or initial + monthly == 0:
        raise ValueError("Invest a lump sum, a monthly amount, or both")
    if not 1 <= months <= MAX_MONTHS:
        raise ValueError(f"Duration must be 1-{MAX_MONTHS} months")
    if not -0.5 < annual_return < 1.0 or not 0 <= annual_volatility < 1.5:
        raise ValueError("Return or volatility is outside a plausible range")
    if not 100 <= paths <= MAX_PATHS:
        raise ValueError(f"Paths must be 100-{MAX_PATHS}")

    sigma = annual_volatility / math.sqrt(12)
    # Monthly log-return mean so that E[gross monthly return] matches the annual expectation.
    mu = math.log(1 + annual_return) / 12 - sigma * sigma / 2
    rng = random.Random(seed)  # noqa: S311 - seeded for reproducible simulations, not security
    finals: list[float] = []
    drawdowns: list[float] = []
    invested = initial + monthly * months
    for _ in range(paths):
        value, peak, worst = float(initial), 0.0, 0.0
        for _m in range(months):
            value = (value + monthly) * math.exp(rng.gauss(mu, sigma))
            peak = max(peak, value)
            worst = max(worst, 1 - value / peak) if peak > 0 else worst
        finals.append(value)
        drawdowns.append(worst)
    finals.sort()
    drawdowns.sort()

    def pct(q: float) -> int:
        return round(finals[min(len(finals) - 1, int(q * len(finals)))])

    return Simulation(
        months=months,
        invested=invested,
        p10=pct(0.10),
        p50=pct(0.50),
        p90=pct(0.90),
        probability_of_loss=sum(1 for f in finals if f < invested) / paths,
        median_max_drawdown=drawdowns[len(drawdowns) // 2],
        paths=paths,
        seed=seed,
    )


def deterministic_value(*, initial: int, monthly: int, months: int, annual_rate: float) -> int:
    """Value at a fixed annual rate, compounded monthly (for side-by-side comparison)."""
    r = (1 + annual_rate) ** (1 / 12) - 1
    value = float(initial)
    for _ in range(months):
        value = (value + monthly) * (1 + r)
    return round(value)
