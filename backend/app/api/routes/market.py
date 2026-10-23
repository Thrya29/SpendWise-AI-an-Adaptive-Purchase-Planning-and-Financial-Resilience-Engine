from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select, update

from app.api.deps import SessionDep, UserDep, user_today
from app.core.db import utcnow
from app.core.errors import DomainValidationError, NotFoundError
from app.core.ratelimit import enforce
from app.market.fetcher import SafeFetcher
from app.models.entities import Alert, PlannedItem, PriceObservation
from app.schemas.finance import PlannedItemRead
from app.schemas.market import (
    AlertCount,
    AlertOut,
    ApplyObservationIn,
    CheckOut,
    FxOut,
    ObservationOut,
    PreviewOut,
    PreviewRequest,
    QuoteIn,
)
from app.services import fx_service, market_service
from app.services.repository import OwnedRepository

router = APIRouter(tags=["market"])


async def get_fetcher() -> AsyncIterator[SafeFetcher]:
    fetcher = SafeFetcher()
    try:
        yield fetcher
    finally:
        await fetcher.aclose()


FetcherDep = Annotated[SafeFetcher, Depends(get_fetcher)]


async def get_fx_client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as client:
        yield client


FxClientDep = Annotated[httpx.AsyncClient, Depends(get_fx_client)]


@router.post("/market/preview", response_model=PreviewOut)
async def preview_link(body: PreviewRequest, user: UserDep, fetcher: FetcherDep) -> PreviewOut:
    """Read the price a page publishes, without saving anything."""
    await enforce(f"market:{user.id}", limit=20)
    return await market_service.preview(fetcher, str(body.url))


async def _item(session: SessionDep, user: UserDep, item_id: UUID) -> PlannedItem:
    return await OwnedRepository(session, PlannedItem, user.id).get(item_id)


@router.post("/items/{item_id}/price-check", response_model=CheckOut)
async def check_price(
    item_id: UUID, user: UserDep, session: SessionDep, fetcher: FetcherDep
) -> CheckOut:
    await enforce(f"market:{user.id}", limit=20)
    item = await _item(session, user, item_id)
    return await market_service.check_item(session, user, item, fetcher)


@router.get("/items/{item_id}/prices", response_model=list[ObservationOut])
async def price_history(
    item_id: UUID,
    user: UserDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[ObservationOut]:
    await _item(session, user, item_id)
    rows = await session.scalars(
        select(PriceObservation)
        .where(PriceObservation.user_id == user.id, PriceObservation.item_id == item_id)
        .order_by(PriceObservation.observed_at.desc(), PriceObservation.id.desc())
        .limit(limit)
    )
    return [ObservationOut.model_validate(r) for r in rows]


@router.post(
    "/items/{item_id}/prices", response_model=ObservationOut, status_code=status.HTTP_201_CREATED
)
async def record_quote(
    item_id: UUID, body: QuoteIn, user: UserDep, session: SessionDep
) -> ObservationOut:
    """Record a price you were quoted (a local shop, a call, a brochure)."""
    item = await _item(session, user, item_id)
    obs = await market_service.record_quote(
        session, user, item, amount_minor=body.amount_minor, shop=body.source_name, note=body.note
    )
    return ObservationOut.model_validate(obs)


@router.post("/items/{item_id}/prices/{observation_id}/apply", response_model=PlannedItemRead)
async def use_observed_price(
    item_id: UUID,
    observation_id: UUID,
    body: ApplyObservationIn,
    user: UserDep,
    session: SessionDep,
) -> PlannedItemRead:
    item = await _item(session, user, item_id)
    obs = await session.scalar(
        select(PriceObservation).where(
            PriceObservation.id == observation_id, PriceObservation.user_id == user.id
        )
    )
    if obs is None:
        raise NotFoundError("price observation not found")
    await market_service.apply_observation(session, user, item, obs, body.version)
    return PlannedItemRead.model_validate(item)


@router.get("/fx/latest", response_model=FxOut)
async def latest_rates(user: UserDep, session: SessionDep) -> FxOut:
    table = await fx_service.latest_table(session, user_today(user))
    base = user.base_currency
    if table is None or not table.supports(base):
        return FxOut(available=False, base=base, as_of=None, source=None)
    rates = {
        code: table.cross(code, base)
        for code in sorted({*table.rates, table.pivot})
        if code != base
    }
    return FxOut(available=True, base=base, as_of=table.as_of, source=table.source, rates=rates)


@router.post("/fx/refresh", response_model=FxOut)
async def refresh_rates(user: UserDep, session: SessionDep, client: FxClientDep) -> FxOut:
    await enforce(f"fx:{user.id}", limit=5, window_seconds=3600)
    try:
        await fx_service.refresh(session, client)
    except fx_service.FxUnavailableError as exc:
        raise DomainValidationError("Exchange rates are unavailable right now.") from exc
    return await latest_rates(user, session)


@router.get("/alerts", response_model=list[AlertOut])
async def list_alerts(
    user: UserDep,
    session: SessionDep,
    unread: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[AlertOut]:
    query = select(Alert).where(Alert.user_id == user.id)
    if unread:
        query = query.where(Alert.read_at.is_(None))
    rows = await session.scalars(query.order_by(Alert.created_at.desc()).limit(limit))
    return [AlertOut.model_validate(r) for r in rows]


@router.get("/alerts/unread-count", response_model=AlertCount)
async def unread_count(user: UserDep, session: SessionDep) -> AlertCount:
    count = await session.scalar(
        select(func.count()).where(Alert.user_id == user.id, Alert.read_at.is_(None))
    )
    return AlertCount(unread=int(count or 0))


@router.post("/alerts/{alert_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(alert_id: UUID, user: UserDep, session: SessionDep) -> None:
    alert = await OwnedRepository(session, Alert, user.id).get(alert_id)
    alert.read_at = alert.read_at or utcnow()


@router.post("/alerts/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_read(user: UserDep, session: SessionDep) -> None:
    await session.execute(
        update(Alert)
        .where(Alert.user_id == user.id, Alert.read_at.is_(None))
        .values(read_at=utcnow())
    )
