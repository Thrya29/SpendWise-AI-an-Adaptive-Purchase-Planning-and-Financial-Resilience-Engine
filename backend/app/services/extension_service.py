"""Browser extension: narrowly scoped keys, and saving a price the user saw and confirmed."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import utcnow
from app.core.errors import DomainValidationError, NotFoundError, UnauthorizedError
from app.models.entities import (
    ExtensionToken,
    ItemStatus,
    ObservationMethod,
    PlannedItem,
    PriceObservation,
    PriceSource,
    User,
)
from app.schemas.extension import CaptureIn, CaptureOut
from app.services import market_service
from app.services.repository import OwnedRepository

PREFIX = "swx_"
MAX_TOKENS = 5
TOUCH_EVERY = timedelta(hours=1)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def create_token(session: AsyncSession, user: User, label: str) -> tuple[ExtensionToken, str]:
    count = await session.scalar(
        select(func.count()).select_from(ExtensionToken).where(ExtensionToken.user_id == user.id)
    )
    if (count or 0) >= MAX_TOKENS:
        raise DomainValidationError(
            f"You can have up to {MAX_TOKENS} extension keys. Revoke one you no longer use."
        )
    raw = PREFIX + secrets.token_urlsafe(32)
    token = ExtensionToken(user_id=user.id, token_hash=hash_token(raw), hint=raw[-4:], label=label)
    session.add(token)
    await session.flush()
    return token, raw


async def user_for_token(session: AsyncSession, raw: str, now: datetime | None = None) -> User:
    if not raw.startswith(PREFIX) or len(raw) > 100:
        raise UnauthorizedError("Invalid extension key")
    token = await session.scalar(
        select(ExtensionToken).where(ExtensionToken.token_hash == hash_token(raw))
    )
    user = await session.get(User, token.user_id) if token else None
    if token is None or user is None:
        raise UnauthorizedError("This extension key was revoked or never existed")
    now = now or utcnow()
    last = token.last_used_at
    if (
        last is None
        or (last if last.tzinfo else last.replace(tzinfo=now.tzinfo)) < now - TOUCH_EVERY
    ):
        token.last_used_at = now
    return user


async def capture(session: AsyncSession, user: User, req: CaptureIn) -> CaptureOut:
    url = str(req.url)
    items = OwnedRepository(session, PlannedItem, user.id)
    created = False
    if req.item_id is not None:
        try:
            item = await items.get(req.item_id)
        except NotFoundError as exc:
            raise DomainValidationError("That item is not one of yours") from exc
        if item.currency != req.currency:
            raise DomainValidationError(
                f"'{item.name}' is priced in {item.currency}, but this page shows {req.currency}."
            )
    else:
        assert req.new_item is not None
        item = await items.create(
            name=req.new_item.name, tier=req.new_item.tier, kind=req.new_item.kind,
            status=ItemStatus.PLANNED, priority=req.new_item.priority,
            estimated_price_minor=req.price_minor, currency=req.currency,
            price_source=PriceSource.LINK, price_observed_at=utcnow(), url=url,
        )  # fmt: skip
        created = True

    previous = await market_service.latest(session, item)
    obs = PriceObservation(
        user_id=user.id, item_id=item.id, amount_minor=req.price_minor, currency=req.currency,
        method=ObservationMethod.BROWSER, confidence="high", availability=req.availability,
        source_name=market_service.source_name(url), url=url, page_title=req.page_title,
        note="Saved from the browser extension", observed_at=utcnow(),
    )  # fmt: skip
    session.add(obs)
    await session.flush()
    alerts = market_service.price_alerts(item, obs, previous)
    session.add_all(alerts)

    applied = created
    if not created and req.use_price:
        applied = await market_service.apply(session, user, item, obs)
    if item.url is None:
        item.url = url
    return CaptureOut(
        item_id=item.id, item_name=item.name, observation_id=obs.id, created_item=created,
        price_applied=applied, alerts=[a.title for a in alerts],
    )  # fmt: skip
