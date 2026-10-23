"""Calibration study for ``app.domain.forecast.hit_probability`` on synthetic price histories.

The question each forecast answers: "will the price reach the target within H days?"
Ground truth comes from the simulated future, so every forecast can be scored.

Synthetic, by necessity: there is no public dataset of per-user retail price checks. The
generator mimics retail behaviour (sticky prices, periodic sales, rare permanent cuts and
increases, irregular checks). Results describe the method on this process, not on any
specific shop.

Run:  python -m research.forecast_calibration [--samples N] [--seed S] [--out PATH]
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.domain.forecast import Forecast, PricePoint, hit_probability  # noqa: E402

DAY0 = date(2025, 1, 1)
SERIES_DAYS = 300
HORIZONS = (14, 30, 60)
TARGET_RATIOS = (0.80, 0.85, 0.90, 0.93, 0.95, 0.97, 0.99)


def simulate(rng: random.Random) -> list[int]:
    """One product's true daily price (minor units)."""
    regular = rng.uniform(5_000, 200_000) * 100
    sale_rate = rng.uniform(1 / 75, 1 / 12)  # sales per day
    jitter = rng.choice((0.0, 0.0, 0.002, 0.006))  # many shops never move between events
    prices: list[int] = []
    sale_left, sale_depth = 0, 0.0
    for _ in range(SERIES_DAYS):
        if rng.random() < 1 / 150:
            regular *= 1 - rng.uniform(0.04, 0.15)  # permanent cut (new model, clearance)
        if rng.random() < 1 / 250:
            regular *= 1 + rng.uniform(0.03, 0.10)  # price increase
        if jitter:
            regular *= math.exp(rng.gauss(0, jitter))
        if sale_left == 0 and rng.random() < sale_rate:
            sale_left, sale_depth = rng.randint(2, 10), rng.uniform(0.05, 0.30)
        price = regular * (1 - sale_depth) if sale_left > 0 else regular
        sale_left = max(0, sale_left - 1)
        prices.append(max(100, round(price)))
    return prices


@dataclass(frozen=True)
class Sample:
    probability: float
    outcome: bool
    confidence: str
    horizon: int


def draw(rng: random.Random) -> Sample | None:
    truth = simulate(rng)
    horizon = rng.choice(HORIZONS)
    t0 = rng.randint(45, SERIES_DAYS - horizon - 1)
    # The user checks the price every 1-3 days (worker cadence plus manual checks).
    observed, day = [], rng.randint(0, 3)
    while day <= t0:
        observed.append(PricePoint(DAY0 + timedelta(days=day), truth[day]))
        day += rng.randint(1, 3)
    if observed[-1].day != DAY0 + timedelta(days=t0):
        observed.append(PricePoint(DAY0 + timedelta(days=t0), truth[t0]))
    target = max(1, round(truth[t0] * rng.choice(TARGET_RATIOS)))
    result = hit_probability(observed, target, horizon)
    if not isinstance(result, Forecast):
        return None
    outcome = min(truth[t0 + 1 : t0 + horizon + 1]) <= target
    return Sample(result.probability, outcome, result.confidence.value, horizon)


def brier(samples: list[Sample]) -> float:
    return sum((s.probability - s.outcome) ** 2 for s in samples) / len(samples)


def reliability(samples: list[Sample], bins: int = 10) -> list[tuple[str, int, float, float]]:
    rows = []
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        last = b == bins - 1
        group = [s for s in samples if lo <= s.probability < hi or (last and s.probability == 1)]
        if group:
            rows.append((
                f"{lo:.1f}–{hi:.1f}", len(group),
                sum(s.probability for s in group) / len(group),
                sum(s.outcome for s in group) / len(group),
            ))  # fmt: skip
    return rows


def expected_calibration_error(samples: list[Sample]) -> float:
    return sum(n * abs(p - o) for _, n, p, o in reliability(samples)) / len(samples)


def run(n: int, seed: int) -> dict[str, object]:
    rng = random.Random(seed)
    samples: list[Sample] = []
    while len(samples) < n:
        s = draw(rng)
        if s is not None:
            samples.append(s)
    base_rate = sum(s.outcome for s in samples) / len(samples)
    climatology = sum((base_rate - s.outcome) ** 2 for s in samples) / len(samples)
    model_brier = brier(samples)
    by_method = {c: [s for s in samples if s.confidence == c] for c in ("high", "medium", "low")}
    return {
        "samples": samples,
        "base_rate": base_rate,
        "brier": model_brier,
        "climatology_brier": climatology,
        "skill": 1 - model_brier / climatology,
        "ece": expected_calibration_error(samples),
        "by_method": {k: (len(v), brier(v) if v else float("nan")) for k, v in by_method.items()},
    }


def report(result: dict[str, object], n: int, seed: int) -> str:
    samples = result["samples"]
    assert isinstance(samples, list)
    lines = [
        "# Forecast calibration (synthetic)",
        "",
        f"Generated by `python -m research.forecast_calibration --samples {n} --seed {seed}`.",
        "Synthetic retail price histories: sticky prices, periodic sales (5–30% off for",
        "2–10 days), rare permanent cuts and increases, and price checks every 1–3 days. Horizons: "
        f"{', '.join(map(str, HORIZONS))} days. Targets: 80–99% of the current price.",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Forecasts scored | {n} |",
        f"| Base rate (target reached) | {result['base_rate']:.3f} |",
        f"| Brier score (lower is better) | **{result['brier']:.4f}** |",
        "| Climatology Brier (always predict the true base rate) | "
        f"{result['climatology_brier']:.4f} |",
        f"| Brier skill score vs climatology | **{result['skill']:.3f}** |",
        f"| Expected calibration error | {result['ece']:.3f} |",
        "",
        "The climatology baseline is given the true base rate in hindsight, which flatters it.",
        "",
        "## By confidence label",
        "",
        "| Confidence | Forecasts | Brier |",
        "|---|---|---|",
    ]
    by_method = result["by_method"]
    assert isinstance(by_method, dict)
    lines += [f"| {m} | {c} | {b:.4f} |" for m, (c, b) in by_method.items()]
    lines += [
        "",
        "## Reliability",
        "",
        "When the forecast says *p*, the target should be reached about *p* of the time.",
        "",
        "| Forecast bin | Forecasts | Mean forecast | Observed frequency |",
        "|---|---|---|---|",
    ]
    lines += [f"| {b} | {c} | {p:.2f} | {o:.2f} |" for b, c, p, o in reliability(samples)]
    lines += [
        "",
        "## Method history",
        "",
        "A first version counted overlapping H-day windows and fell back to a random-walk",
        "first-passage model. On the tuning seed it scored a Brier skill of **-0.108** (worse than",
        'climatology) with an expected calibration error of 0.196: it said "5%" for events that',
        "happened 41% of the time. Overlapping windows over a few sales overstated the evidence,",
        "and random walks fit sticky, jumpy retail prices poorly. It was replaced by the",
        "drop-episode Poisson method above. Its priors (reference window, prior episodes and",
        "days) were grid-searched on seed 7, and this report uses held-out seed 11.",
        "",
        "## Caveats",
        "",
        "* Real shops may behave differently (flash sales, algorithmic repricing). Measure again",
        "  on real price histories as they accumulate before quoting accuracy for a specific shop.",
        "* Forecasts are withheld entirely when history is short (< 5 checks or < 14 days).",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--samples", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=11)  # held out: priors were tuned on seed 7
    default_out = ROOT / "docs" / "results" / "forecast-calibration.md"
    parser.add_argument("--out", type=Path, default=default_out)
    args = parser.parse_args()
    result = run(args.samples, args.seed)
    text = report(result, args.samples, args.seed)
    args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
