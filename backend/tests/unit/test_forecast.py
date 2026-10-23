from datetime import date, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.forecast import (
    PRIOR_DAYS,
    PRIOR_EPISODES,
    Confidence,
    Forecast,
    NoForecast,
    PricePoint,
    count_episodes,
    daily_series,
    hit_probability,
)

D0 = date(2026, 1, 1)


def pts(prices: list[int], every: int = 1) -> list[PricePoint]:
    return [PricePoint(D0 + timedelta(days=i * every), p) for i, p in enumerate(prices)]


def test_daily_series_carries_forward_and_keeps_last_of_day() -> None:
    points = [PricePoint(D0, 100), PricePoint(D0, 90), PricePoint(D0 + timedelta(days=3), 80)]
    assert daily_series(points) == [90, 90, 90, 80]
    assert daily_series([]) == []
    with pytest.raises(ValueError):
        daily_series([PricePoint(D0, 0)])


def test_insufficient_history_is_reported_not_guessed() -> None:
    few = hit_probability(pts([100, 99, 98]), 90, 30)
    assert isinstance(few, NoForecast) and few.observations == 3
    assert "Not enough price history" in few.reason
    short_span = hit_probability(pts([100, 99, 98, 97, 96, 95]), 90, 30)
    assert isinstance(short_span, NoForecast) and short_span.span_days == 5


def test_a_long_sale_is_one_episode() -> None:
    sale = [100] * 10 + [85] * 6 + [100] * 10 + [88] * 2 + [100] * 5
    assert count_episodes(sale, 0.90) == 2
    assert count_episodes(sale, 0.86) == 1  # only the deeper sale qualifies
    assert count_episodes(sale, 0.50) == 0
    # Two separate 50%-off dips inside one long 20%-off sale: the shallow level is never
    # credited with fewer dips than the deeper one.
    nested = [100] * 10 + [50, 80, 80, 50] + [100] * 10
    assert count_episodes(nested, 0.5) == 2 and count_episodes(nested, 0.8) == 2


def test_regular_sales_make_a_drop_likely_and_deep_drops_unlikely() -> None:
    # 130 days: a 10%-off sale for 3 days every 20 days, so 6 sale episodes.
    series = [90_000 if (d % 20) in (10, 11, 12) else 100_000 for d in range(130)]
    f = hit_probability(pts(series), 90_000, 30)
    assert isinstance(f, Forecast) and f.episodes == 6
    expected_rate = (6 + PRIOR_EPISODES) / (129 + PRIOR_DAYS)
    assert f.probability == pytest.approx(1 - 2.718281828459045 ** (-expected_rate * 30), abs=1e-3)
    assert f.probability > 0.7 and f.confidence is Confidence.HIGH
    deep = hit_probability(pts(series), 80_000, 30)
    assert isinstance(deep, Forecast) and deep.episodes == 0 and deep.probability < f.probability


def test_target_measured_against_regular_price_during_a_sale() -> None:
    # Currently on sale at 90k (regular 100k); 85k needs a 15%-off episode, which never happened.
    series = [100_000] * 60 + [90_000] * 3
    f = hit_probability(pts(series), 85_000, 30)
    assert isinstance(f, Forecast) and f.reference == 100_000 and f.current == 90_000
    assert f.episodes == 0
    assert f.probability == pytest.approx(
        1 - 2.718281828459045 ** (-(PRIOR_EPISODES / (62 + PRIOR_DAYS)) * 30), abs=1e-3
    )


def test_already_cheap_enough_and_descriptive_range() -> None:
    series = [100 + (d % 5) for d in range(40)]
    f = hit_probability(pts(series), 1_000, 7)
    assert isinstance(f, Forecast) and f.probability == 1.0
    assert f.recent_low <= f.recent_median <= f.recent_high
    assert (f.recent_low, f.recent_high) == (100, 104)


def test_confidence_reflects_history_and_validation() -> None:
    short = hit_probability(pts([100] * 6, every=4), 95, 30)  # 20 days
    medium = hit_probability(pts([100] * 20, every=3), 95, 30)  # 57 days
    long = hit_probability(pts([100] * 130), 95, 30)
    assert [f.confidence for f in (short, medium, long)] == [  # type: ignore[union-attr]
        Confidence.LOW, Confidence.MEDIUM, Confidence.HIGH,
    ]  # fmt: skip
    with pytest.raises(ValueError):
        hit_probability(pts([1] * 20), 0, 30)
    with pytest.raises(ValueError):
        hit_probability(pts([1] * 20), 1, 0)


prices = st.lists(st.integers(1_000, 1_000_000), min_size=15, max_size=120)


@settings(max_examples=200, deadline=None)
@given(prices, st.floats(0.5, 1.2), st.integers(1, 90))
def test_probability_is_bounded_and_monotonic(series: list[int], frac: float, horizon: int) -> None:
    current = series[-1]
    target = max(1, int(current * frac))
    f = hit_probability(pts(series), target, horizon)
    assert isinstance(f, Forecast)
    assert 0.0 < f.probability <= 1.0
    higher = hit_probability(pts(series), max(target, int(current * min(frac + 0.1, 1.3))), horizon)
    longer = hit_probability(pts(series), target, min(horizon + 15, 365))
    assert isinstance(higher, Forecast) and isinstance(longer, Forecast)
    assert higher.probability >= f.probability - 1e-9  # a higher target is never less likely
    assert longer.probability >= f.probability - 1e-9  # neither is more time
