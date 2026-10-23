"""Reference exchange rates: fetch daily, store exactly, convert with provenance."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domain.fx import RateTable, RateUnavailableError, parse_rate
from app.domain.money import SUPPORTED_CURRENCIES, Money
from app.models.entities import FxRate

logger = logging.getLogger("spendwise.fx")

SOURCE = "European Central Bank reference rate (via Frankfurter)"
MAX_RATE_AGE = timedelta(days=10)  # ECB skips weekends and TARGET holidays


class FxUnavailableError(Exception):
    pass


async def fetch_reference_rates(client: httpx.AsyncClient) -> tuple[date, dict[str, Decimal]]:
    """Latest EUR-based ECB rates for the currencies SpendWise supports."""
    try:
        response = await client.get(get_settings().fx_url, timeout=15.0)
        response.raise_for_status()
        data = response.json()
        if data.get("base") != "EUR":
            raise FxUnavailableError("Unexpected base currency")
        rate_date = date.fromisoformat(str(data["date"]))
        rates = {
            code: parse_rate(value)
            for code, value in dict(data["rates"]).items()
            if code in SUPPORTED_CURRENCIES
        }
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise FxUnavailableError(str(exc)) from exc
    if not rates:
        raise FxUnavailableError("No usable rates")
    return rate_date, rates


async def store_rates(session: AsyncSession, rate_date: date, rates: dict[str, Decimal]) -> int:
    existing = set(
        await session.scalars(
            select(FxRate.currency).where(FxRate.pivot == "EUR", FxRate.rate_date == rate_date)
        )
    )
    added = 0
    for code, rate in sorted(rates.items()):
        if code not in existing:
            session.add(
                FxRate(
                    pivot="EUR", currency=code, rate=str(rate), rate_date=rate_date, source=SOURCE
                )
            )
            added += 1
    await session.flush()
    return added


async def refresh(session: AsyncSession, client: httpx.AsyncClient) -> int:
    rate_date, rates = await fetch_reference_rates(client)
    added = await store_rates(session, rate_date, rates)
    logger.info("fx_refreshed", extra={"rate_date": str(rate_date), "added": added})
    return added


async def latest_table(session: AsyncSession, today: date) -> RateTable | None:
    """The most recent stored table, or None if missing or older than ``MAX_RATE_AGE``."""
    newest = await session.scalar(select(func.max(FxRate.rate_date)).where(FxRate.pivot == "EUR"))
    if newest is None or today - newest > MAX_RATE_AGE:
        return None
    rows = await session.scalars(
        select(FxRate).where(FxRate.pivot == "EUR", FxRate.rate_date == newest)
    )
    return RateTable("EUR", {r.currency: Decimal(r.rate) for r in rows}, newest, SOURCE)


@dataclass(frozen=True, slots=True)
class Converter:
    """Converts amounts into one target currency and explains each conversion."""

    target: str
    table: RateTable | None

    def convert(self, amount: Money, label: str) -> tuple[Money | None, str | None]:
        """Return (converted amount or None, warning text)."""
        if amount.currency == self.target:
            return amount, None
        if self.table is None:
            return None, (
                f"{label} ({amount.currency}) excluded: no recent exchange rate is available."
            )
        try:
            converted = self.table.convert(amount, self.target)
            rate = self.table.cross(amount.currency, self.target)
        except RateUnavailableError:
            return None, (
                f"{label} ({amount.currency}) excluded: no reference rate for "
                f"{amount.currency} to {self.target}."
            )
        return converted, (
            f"{label} converted from {amount.currency} at 1 {amount.currency} = "
            f"{rate.quantize(Decimal('0.0001'))} {self.target} "
            f"({self.table.as_of.isoformat()} reference rate)."
        )
