from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from app.ai import service as ai
from app.ai.schemas import ParseContext
from app.api.deps import SessionDep, UserDep, user_today
from app.core.errors import ConflictError
from app.core.ratelimit import enforce
from app.domain.money import Money, validate_currency
from app.models.entities import DeadlineType, ItemKind, Plan, PlanStatus, Tier
from app.schemas.planner import (
    ApplyRequest,
    ApplyResponse,
    ItemDraftOut,
    ParseItemRequest,
    PlanListItem,
    PlanOut,
    PlanRequest,
)
from app.services import planner_service
from app.services.repository import OwnedRepository

router = APIRouter(prefix="/planner", tags=["planner"])
assistant_router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.post("/plans", response_model=PlanOut, status_code=status.HTTP_201_CREATED)
async def create_plan(body: PlanRequest, user: UserDep, session: SessionDep) -> PlanOut:
    """Solve for the best purchase schedule. Nothing changes until the plan is applied."""
    await enforce(f"planner:{user.id}", limit=30)
    return await planner_service.create_plan(session, user, body, user_today(user))


@router.get("/plans", response_model=list[PlanListItem])
async def list_plans(
    user: UserDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[PlanListItem]:
    rows = await session.scalars(
        select(Plan).where(Plan.user_id == user.id).order_by(Plan.created_at.desc()).limit(limit)
    )
    out = []
    for p in rows:
        decisions = p.result.get("decisions", [])
        out.append(
            PlanListItem(
                id=p.id,
                created_at=p.created_at,
                status=p.status,
                horizon_months=p.horizon_months,
                decisions=len(decisions),
                changes=sum(1 for d in decisions if any(d.get("changes", {}).values())),
            )
        )
    return out


@router.get("/plans/{plan_id}", response_model=PlanOut)
async def read_plan(plan_id: UUID, user: UserDep, session: SessionDep) -> PlanOut:
    return await planner_service.get_plan(session, user, plan_id, user_today(user))


@router.post("/plans/{plan_id}/apply", response_model=ApplyResponse)
async def apply_plan(
    plan_id: UUID, body: ApplyRequest, user: UserDep, session: SessionDep
) -> ApplyResponse:
    """Apply the approved changes (target dates and statuses) to your items."""
    return await planner_service.apply_plan(session, user, plan_id, body, user_today(user))


@router.post("/plans/{plan_id}/discard", status_code=status.HTTP_204_NO_CONTENT)
async def discard_plan(plan_id: UUID, user: UserDep, session: SessionDep) -> None:
    plan = await OwnedRepository(session, Plan, user.id).get(plan_id)
    if plan.status is not PlanStatus.DRAFT:
        raise ConflictError(f"This plan was already {plan.status.value}.")
    plan.status = PlanStatus.DISCARDED


def _deadline(value: str | None, *, has_date: bool) -> DeadlineType:
    """A deadline needs a date: without one the item is always flexible."""
    if not has_date:
        return DeadlineType.NONE
    return DeadlineType(value) if value else DeadlineType.SOFT


@assistant_router.post("/parse-item", response_model=ItemDraftOut)
async def parse_item(body: ParseItemRequest, user: UserDep) -> ItemDraftOut:
    """Turn a note like "salon visit next month around 1500" into a draft item to review."""
    await enforce(f"assistant:{user.id}", limit=20)
    ctx = ParseContext(today=user_today(user), base_currency=user.base_currency, city=user.city)
    result = await ai.parse_item(user, body.text, ctx)
    draft = result.value
    notice = result.notice

    currency = user.base_currency
    if draft.currency:
        try:
            currency = validate_currency(draft.currency)
        except ValueError:
            notice = f"{draft.currency} is not supported; using {user.base_currency}."
    price: int | None = None
    if draft.amount is not None:
        minor = Money.from_decimal(draft.amount, currency).amount_minor
        price = minor if 0 <= minor <= 10**15 else None

    missing = [
        label for label, value in (("price", price), ("date", draft.target_date)) if value is None
    ]
    return ItemDraftOut(
        name=draft.name,
        tier=Tier(draft.tier or "want"),
        kind=ItemKind(draft.kind or "product"),
        priority=draft.priority or 3,
        estimated_price_minor=price,
        currency=currency,
        quantity=draft.quantity or 1,
        target_date=draft.target_date,
        deadline_type=_deadline(draft.deadline_type, has_date=draft.target_date is not None),
        lead_time_days=0,
        location=draft.location,
        missing=missing,
        source=result.source,
        notice=notice,
    )
