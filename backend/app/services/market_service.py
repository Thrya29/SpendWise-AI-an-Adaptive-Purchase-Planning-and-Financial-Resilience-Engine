"""Price checks with provenance, consent-based price updates, and alert rules."""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.formatting import format_amount
from app.core.db import utcnow
from app.core.errors import ConflictError, DomainValidationError
from app.domain.money import Money
from app.market.extract import Extraction, PriceCandidate, extract
from app.market.fetcher import FetchError, SafeFetcher
from app.models.entities import (
    Alert,
    AlertKind,
    Availability,
    ObservationMethod,
    PlannedItem,
    PriceObservation,
    PriceSource,
    User,
)
from app.schemas.market import CheckOut, ObservationOut, PreviewOut
from app.services.repository import OwnedRepository

logger = logging.getLogger("spendwise.market")

DROP_ALERT_RATIO = Decimal("0.05")
FAILURES_BEFORE_ALERT = 3


def source_name(url: str) -> str:
    host = (urlsplit(url).hostname or url).lower()
    return host[4:] if host.startswith("www.") else host


def _to_minor(candidate: PriceCandidate) -> int | None:
    try:
        minor = Money.from_decimal(candidate.amount, candidate.currency).amount_minor
    except ValueError:
        return None
    return minor if 0 < minor <= 10**15 else None


def _not_found_message(extraction: Extraction) -> str:
    return (
        "This page does not publish a machine-readable price. "
        "Many shops show prices only to browsers. Enter the price yourself or record a quote."
        if extraction.title
        else "No product information was found on this page."
    )


async def preview(fetcher: SafeFetcher, url: str) -> PreviewOut:
    try:
        page = await fetcher.fetch(url)
    except FetchError as exc:
        return PreviewOut(
            url=url, source_name=source_name(url), title=None, found=False, price_minor=None,
            currency=None, method=None, confidence=None, availability=Availability.UNKNOWN,
            message=exc.reason,
        )  # fmt: skip
    extraction = extract(page.html)
    best = extraction.best
    minor = _to_minor(best) if best else None
    if best is None or minor is None:
        return PreviewOut(
            url=page.url, source_name=source_name(page.url), title=extraction.title, found=False,
            price_minor=None, currency=None, method=None, confidence=None,
            availability=Availability.UNKNOWN, message=_not_found_message(extraction),
        )  # fmt: skip
    note = " This is the lowest price in a range." if best.low else ""
    return PreviewOut(
        url=page.url, source_name=source_name(page.url), title=best.name or extraction.title,
        found=True, price_minor=minor, currency=best.currency,
        method=ObservationMethod(best.method.value), confidence=best.confidence,
        availability=Availability(best.availability.value),
        message=f"Price published by {source_name(page.url)}.{note}",
    )  # fmt: skip


async def latest(session: AsyncSession, item: PlannedItem) -> PriceObservation | None:
    return await session.scalar(
        select(PriceObservation)
        .where(PriceObservation.item_id == item.id)
        .order_by(PriceObservation.observed_at.desc(), PriceObservation.id.desc())
        .limit(1)
    )


def _alert(item: PlannedItem, kind: AlertKind, title: str, body: str) -> Alert:
    return Alert(
        user_id=item.user_id, item_id=item.id, kind=kind, title=title[:200], body=body[:1000]
    )


def price_alerts(
    item: PlannedItem, new: PriceObservation, previous: PriceObservation | None
) -> list[Alert]:
    """Alert rules for a fresh observation (same-currency comparisons only)."""
    alerts: list[Alert] = []
    money = format_amount(new.amount_minor, new.currency)
    same = previous is not None and previous.currency == new.currency
    if item.max_price_minor is not None and new.currency == item.currency:
        was_above = previous is None or not same or previous.amount_minor > item.max_price_minor
        if new.amount_minor <= item.max_price_minor and was_above:
            alerts.append(_alert(
                item, AlertKind.PRICE_TARGET, f"{item.name} is within your limit",
                f"{new.source_name} lists it at {money}, at or below your maximum of "
                f"{format_amount(item.max_price_minor, item.currency)}.",
            ))  # fmt: skip
    if same and previous is not None:
        drop = previous.amount_minor - new.amount_minor
        if drop > 0 and Decimal(drop) >= Decimal(previous.amount_minor) * DROP_ALERT_RATIO:
            alerts.append(_alert(
                item, AlertKind.PRICE_DROP, f"Price drop: {item.name}",
                f"Now {money} at {new.source_name}, down from "
                f"{format_amount(previous.amount_minor, previous.currency)}.",
            ))  # fmt: skip
        if (
            previous.availability is Availability.OUT_OF_STOCK
            and new.availability is Availability.IN_STOCK
        ):
            alerts.append(_alert(
                item, AlertKind.BACK_IN_STOCK, f"{item.name} is back in stock",
                f"{new.source_name} shows it in stock at {money}.",
            ))  # fmt: skip
    return alerts


async def check_item(
    session: AsyncSession, user: User, item: PlannedItem, fetcher: SafeFetcher
) -> CheckOut:
    """Fetch the item's link now, record what was found, and apply it if tracking is on."""
    if not item.url:
        raise DomainValidationError("Add a product link to this item first.")
    now = utcnow()
    item.last_checked_at = now
    try:
        page = await fetcher.fetch(item.url)
    except FetchError as exc:
        return await _record_failure(session, item, exc.reason)
    extraction = extract(page.html)
    best = extraction.best
    minor = _to_minor(best) if best else None
    if best is None or minor is None:
        return await _record_failure(session, item, _not_found_message(extraction))

    previous = await latest(session, item)
    obs = PriceObservation(
        user_id=user.id, item_id=item.id, amount_minor=minor, currency=best.currency,
        method=ObservationMethod(best.method.value), confidence=best.confidence,
        availability=Availability(best.availability.value), source_name=source_name(page.url),
        url=page.url[:2048], page_title=(best.name or extraction.title or None),
        note="Lowest price in a range" if best.low else None, observed_at=now,
    )  # fmt: skip
    session.add(obs)
    item.last_check_error = None
    item.failed_checks = 0
    await session.flush()
    for alert in price_alerts(item, obs, previous):
        session.add(alert)

    applied = False
    if item.track_price and obs.currency == item.currency:
        applied = await apply(session, user, item, obs)
    message = f"Found {format_amount(minor, best.currency)} at {obs.source_name}."
    if item.track_price and obs.currency != item.currency:
        message += f" Not applied: the item is priced in {item.currency}."
    return CheckOut(
        found=True, message=message, observation=ObservationOut.model_validate(obs),
        applied_to_item=applied, item_version=item.version,
    )  # fmt: skip


async def _record_failure(session: AsyncSession, item: PlannedItem, reason: str) -> CheckOut:
    item.last_check_error = reason[:300]
    item.failed_checks = min(item.failed_checks + 1, 1000)
    if item.failed_checks == FAILURES_BEFORE_ALERT and item.track_price:
        session.add(
            _alert(
                item, AlertKind.CHECK_FAILING, f"Can't check the price of {item.name}",
                f"The last {FAILURES_BEFORE_ALERT} checks failed: {reason}",
            )
        )  # fmt: skip
    await session.flush()
    return CheckOut(
        found=False, message=reason, observation=None, applied_to_item=False,
        item_version=item.version,
    )  # fmt: skip


async def apply(
    session: AsyncSession, user: User, item: PlannedItem, obs: PriceObservation
) -> bool:
    if item.estimated_price_minor == obs.amount_minor and item.price_source is PriceSource.LINK:
        return False
    repo = OwnedRepository(session, PlannedItem, user.id)
    source = PriceSource.QUOTE if obs.method is ObservationMethod.MANUAL else PriceSource.LINK
    await repo.update(
        item.id,
        item.version,
        {
            "estimated_price_minor": obs.amount_minor,
            "price_source": source,
            "price_observed_at": obs.observed_at,
        },
    )
    return True


async def record_quote(
    session: AsyncSession,
    user: User,
    item: PlannedItem,
    *,
    amount_minor: int,
    shop: str,
    note: str | None,
    now: datetime | None = None,
) -> PriceObservation:
    previous = await latest(session, item)
    obs = PriceObservation(
        user_id=user.id, item_id=item.id, amount_minor=amount_minor, currency=item.currency,
        method=ObservationMethod.MANUAL, confidence="high", availability=Availability.UNKNOWN,
        source_name=shop, url=None, page_title=None, note=note, observed_at=now or utcnow(),
    )  # fmt: skip
    session.add(obs)
    await session.flush()
    for alert in price_alerts(item, obs, previous):
        session.add(alert)
    return obs


async def apply_observation(
    session: AsyncSession, user: User, item: PlannedItem, obs: PriceObservation, version: int
) -> PlannedItem:
    """Use an observed price as the item's estimate (explicit user action)."""
    if obs.item_id != item.id:
        raise DomainValidationError("That price belongs to a different item.")
    if obs.currency != item.currency:
        raise DomainValidationError(
            f"That price is in {obs.currency}, but the item is priced in {item.currency}."
        )
    if item.version != version:
        raise ConflictError(
            "This item changed elsewhere. Reload and try again.",
            extra={"current_version": item.version},
        )
    await apply(session, user, item, obs)
    return item
