"""Background worker: refresh exchange rates and re-check tracked prices.

Run with ``python -m app.worker``. Each job runs in its own transaction so one
failure never blocks the rest; requests to the same website are spaced out.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
from sqlalchemy import func, or_, select

from app.core.config import get_settings
from app.core.db import dispose_engine, get_sessionmaker, utcnow
from app.core.errors import ConflictError
from app.core.logging import configure_logging
from app.core.ratelimit import reset_rate_limiter
from app.market.fetcher import SafeFetcher
from app.models.entities import FxRate, ItemStatus, PlannedItem, User
from app.services import fx_service, market_service

logger = logging.getLogger("spendwise.worker")

TICK_SECONDS = 60
BATCH = 20
SAME_SITE_SPACING_S = 10.0


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)  # SQLite drops tzinfo


async def refresh_fx_if_due(client: httpx.AsyncClient) -> bool:
    hours = get_settings().fx_refresh_hours
    async with get_sessionmaker()() as session:
        last = await session.scalar(select(func.max(FxRate.fetched_at)))
        if last is not None and _aware(last) > utcnow() - timedelta(hours=hours):
            return False
        try:
            await fx_service.refresh(session, client)
            await session.commit()
        except fx_service.FxUnavailableError:
            logger.warning("fx_refresh_failed", exc_info=True)
            await session.rollback()
            return False
    return True


async def due_items(limit: int = BATCH) -> list[tuple[UUID, UUID]]:
    """(item_id, user_id) pairs whose tracked price is due for a check."""
    cutoff = utcnow() - timedelta(hours=get_settings().price_check_hours)
    async with get_sessionmaker()() as session:
        rows = await session.execute(
            select(PlannedItem.id, PlannedItem.user_id)
            .where(
                PlannedItem.track_price,
                PlannedItem.url.is_not(None),
                PlannedItem.status.in_([ItemStatus.PLANNED, ItemStatus.POSTPONED]),
                or_(PlannedItem.last_checked_at.is_(None), PlannedItem.last_checked_at < cutoff),
            )
            .order_by(PlannedItem.last_checked_at.is_not(None), PlannedItem.last_checked_at)
            .limit(limit)
        )
        return [(i, u) for i, u in rows.all()]


async def check_one(item_id: UUID, user_id: UUID, fetcher: SafeFetcher) -> bool:
    async with get_sessionmaker()() as session:
        user = await session.get(User, user_id)
        item = await session.get(PlannedItem, item_id)
        if user is None or item is None or item.user_id != user.id:
            return False
        try:
            result = await market_service.check_item(session, user, item, fetcher)
            await session.commit()
        except ConflictError:
            await session.rollback()  # the user edited the item meanwhile; retry next cycle
            return False
        logger.info("price_checked", extra={"item_id": str(item_id), "found": result.found})
        return result.found


async def check_due_prices(
    fetcher: SafeFetcher, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
) -> int:
    found = 0
    last_hit: dict[str, float] = {}
    loop = asyncio.get_running_loop()
    for item_id, user_id in await due_items():
        async with get_sessionmaker()() as session:
            url = await session.scalar(select(PlannedItem.url).where(PlannedItem.id == item_id))
        site = market_service.source_name(url or "")
        wait = SAME_SITE_SPACING_S - (loop.time() - last_hit.get(site, -1e9))
        if wait > 0:
            await sleep(wait)
        last_hit[site] = loop.time()
        try:
            found += await check_one(item_id, user_id, fetcher)
        except Exception:  # one bad item must not stop the batch
            logger.exception("price_check_crashed", extra={"item_id": str(item_id)})
    return found


async def run_once(client: httpx.AsyncClient, fetcher: SafeFetcher) -> None:
    await refresh_fx_if_due(client)
    await check_due_prices(fetcher)


async def main() -> None:
    configure_logging(get_settings().log_level)
    reset_rate_limiter()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # Windows dev machines
            loop.add_signal_handler(sig, stop.set)
    logger.info("worker_started")
    async with httpx.AsyncClient() as client:
        fetcher = SafeFetcher()
        try:
            while not stop.is_set():
                try:
                    await run_once(client, fetcher)
                except Exception:
                    logger.exception("worker_cycle_failed")
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=TICK_SECONDS)
        finally:
            await fetcher.aclose()
            await dispose_engine()
    logger.info("worker_stopped")


if __name__ == "__main__":
    asyncio.run(main())
