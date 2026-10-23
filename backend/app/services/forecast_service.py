"""Forecasts for an item from its own price history, with plain-language context."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.formatting import format_amount
from app.domain.forecast import (
    MAX_HORIZON_DAYS,
    Forecast,
    PricePoint,
    hit_probability,
)
from app.models.entities import PlannedItem, PriceObservation
from app.schemas.market import ForecastOut

DEFAULT_HORIZON_DAYS = 30
DEFAULT_DISCOUNT = 0.90  # when the user set no maximum price: "10% off"


async def price_points(session: AsyncSession, item: PlannedItem) -> list[PricePoint]:
    rows = await session.scalars(
        select(PriceObservation)
        .where(PriceObservation.item_id == item.id, PriceObservation.currency == item.currency)
        .order_by(PriceObservation.observed_at)
    )
    return [PricePoint(r.observed_at.date(), r.amount_minor) for r in rows]


def default_horizon(item: PlannedItem, today: date) -> int:
    latest = item.target_date - timedelta(days=item.lead_time_days) if item.target_date else None
    if latest is None or latest <= today:
        return DEFAULT_HORIZON_DAYS
    return min((latest - today).days, MAX_HORIZON_DAYS)


def default_target(item: PlannedItem) -> int:
    if item.max_price_minor:
        return item.max_price_minor
    return max(1, round(item.estimated_price_minor * DEFAULT_DISCOUNT))


async def item_forecast(
    session: AsyncSession,
    item: PlannedItem,
    today: date,
    *,
    target: int | None = None,
    horizon_days: int | None = None,
) -> ForecastOut:
    target = target or default_target(item)
    horizon = horizon_days or default_horizon(item, today)
    result = hit_probability(await price_points(session, item), target, horizon)
    by = today + timedelta(days=horizon)
    if not isinstance(result, Forecast):
        return ForecastOut(
            available=False, reason=result.reason, currency=item.currency, target_minor=target,
            horizon_days=horizon, by_date=by, observations=result.observations,
            span_days=result.span_days,
        )  # fmt: skip
    cur = item.currency
    basis = (
        f"Based on {result.observations} price checks over {result.span_days} days. "
        f"The price has dropped this far {result.episodes} time(s) below its regular level "
        f"of about {format_amount(result.reference, cur)}."
    )
    return ForecastOut(
        available=True, reason=None, currency=cur, target_minor=target, horizon_days=horizon,
        by_date=by, observations=result.observations, span_days=result.span_days,
        probability=result.probability, confidence=result.confidence.value,
        current_minor=result.current, reference_minor=result.reference, episodes=result.episodes,
        recent_low_minor=result.recent_low, recent_median_minor=result.recent_median,
        recent_high_minor=result.recent_high, basis=basis,
    )  # fmt: skip
