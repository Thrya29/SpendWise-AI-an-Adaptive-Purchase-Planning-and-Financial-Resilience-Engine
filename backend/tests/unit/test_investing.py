import math
from datetime import date, timedelta

import pytest

from app.domain.investing import (
    NavPoint,
    deterministic_value,
    fund_stats,
    simulate,
)

D0 = date(2020, 1, 1)


def series(daily_growth: float, days: int, start: float = 100.0) -> list[NavPoint]:
    return [NavPoint(D0 + timedelta(days=d), start * (1 + daily_growth) ** d) for d in range(days)]


def test_fund_stats_recovers_known_growth() -> None:
    annual = 0.12
    daily = (1 + annual) ** (1 / 365.25) - 1
    s = fund_stats(series(daily, 6 * 365))
    assert s is not None and set(s.cagr) == {1, 3, 5}
    for years in (1, 3, 5):
        assert s.cagr[years] == pytest.approx(annual, abs=0.002)
    assert s.volatility == pytest.approx(0.0, abs=1e-9) and s.max_drawdown == 0.0


def test_fund_stats_drawdown_volatility_and_short_history() -> None:
    pts = [NavPoint(D0 + timedelta(days=d), v) for d, v in enumerate([100, 120, 90, 110] * 20)]
    s = fund_stats(pts)
    assert s is not None and s.max_drawdown == pytest.approx(0.25)  # 120 -> 90
    assert s.volatility is not None and s.volatility > 0.5
    assert s.cagr == {}  # under a year of history: no annualised returns
    assert fund_stats(series(0.001, 20)) is None
    assert fund_stats([NavPoint(D0, 0)] * 40) is None


def test_simulation_is_seeded_and_ordered() -> None:
    kw = {"initial": 100_000_00, "monthly": 10_000_00, "months": 120,
          "annual_return": 0.11, "annual_volatility": 0.16}  # fmt: skip
    a, b = simulate(**kw), simulate(**kw)
    assert a == b  # deterministic for a given seed
    assert a.invested == 100_000_00 + 10_000_00 * 120
    assert a.p10 < a.p50 < a.p90
    assert 0 <= a.probability_of_loss < 0.2 and 0 < a.median_max_drawdown < 1
    other = simulate(**kw, seed=7)
    assert other.p50 != a.p50


def test_zero_volatility_matches_deterministic_compounding() -> None:
    sim = simulate(initial=0, monthly=5_000_00, months=60, annual_return=0.08,
                   annual_volatility=0.0, paths=100)  # fmt: skip
    expected = deterministic_value(initial=0, monthly=5_000_00, months=60, annual_rate=0.08)
    assert sim.p10 == sim.p50 == sim.p90
    assert sim.p50 == pytest.approx(expected, rel=1e-9)
    assert sim.probability_of_loss == 0


def test_median_tracks_expected_growth_and_more_risk_widens_range() -> None:
    calm = simulate(initial=1_000_000, monthly=0, months=120, annual_return=0.10,
                    annual_volatility=0.05, paths=3_000)  # fmt: skip
    risky = simulate(initial=1_000_000, monthly=0, months=120, annual_return=0.10,
                     annual_volatility=0.30, paths=3_000)  # fmt: skip
    median_growth = 1_000_000 * math.exp(120 * (math.log(1.10) / 12 - 0.05**2 / 24))
    assert calm.p50 == pytest.approx(median_growth, rel=0.02)
    assert (risky.p90 - risky.p10) > (calm.p90 - calm.p10)
    assert risky.probability_of_loss > calm.probability_of_loss


@pytest.mark.parametrize(
    "kw",
    [{"initial": 0, "monthly": 0}, {"months": 0}, {"months": 481}, {"annual_return": 2.0},
     {"annual_volatility": -0.1}, {"paths": 10}, {"initial": -1}],
)  # fmt: skip
def test_simulation_validation(kw: dict) -> None:
    base = {"initial": 1000, "monthly": 100, "months": 12, "annual_return": 0.1,
            "annual_volatility": 0.1}  # fmt: skip
    with pytest.raises(ValueError):
        simulate(**{**base, **kw})


def test_fund_search_ranks_the_exact_fund_first() -> None:
    from app.api.routes.insights import _relevance  # noqa: PLC0415

    names = [
        "UTI - Nifty Next 50 Index Fund - Direct Plan - Growth",
        "UTI Nifty 50 Equal Weight Index Fund - Direct Plan - Growth",
        "UTI Nifty 50 Index Fund - Direct Plan - Growth",
    ]
    ranked = sorted(names, key=lambda n: _relevance(n, "uti nifty 50 index direct growth"))
    assert ranked[0] == "UTI Nifty 50 Index Fund - Direct Plan - Growth"
