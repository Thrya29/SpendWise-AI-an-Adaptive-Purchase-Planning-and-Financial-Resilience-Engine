"""Feedback and monthly check-ins: how the plan worked out in real life."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, status
from sqlalchemy import select

from app.api.deps import SessionDep, UserDep, user_today
from app.core.errors import ConflictError, DomainValidationError
from app.core.ratelimit import enforce
from app.models.entities import Feedback, FeedbackKind, User
from app.schemas.feedback import CheckinDue, CheckinIn, CommentIn, FeedbackRead
from app.services import usage

router = APIRouter(prefix="/feedback", tags=["feedback"])

MIN_DAYS_IN_MONTH = 14  # ask about a month only if the account existed for most of it


def _previous_month(today: date) -> tuple[str, date]:
    last_day = today.replace(day=1) - timedelta(days=1)
    return f"{last_day.year:04d}-{last_day.month:02d}", last_day


async def _checkin_exists(session: SessionDep, user: User, month: str) -> bool:
    found = await session.scalar(
        select(Feedback.id).where(
            Feedback.user_id == user.id,
            Feedback.kind == FeedbackKind.CHECKIN,
            Feedback.month == month,
        )
    )
    return found is not None


@router.post("", response_model=FeedbackRead, status_code=status.HTTP_201_CREATED)
async def send_feedback(body: CommentIn, user: UserDep, session: SessionDep) -> FeedbackRead:
    await enforce(f"feedback:{user.id}", limit=10, window_seconds=3600)
    row = Feedback(
        user_id=user.id, kind=FeedbackKind.COMMENT, rating=body.rating, message=body.message,
        page=body.page,
    )  # fmt: skip
    session.add(row)
    usage.record(session, user, "feedback", user_today(user))
    await session.flush()
    return FeedbackRead.model_validate(row)


@router.get("/checkin", response_model=CheckinDue)
async def checkin_due(user: UserDep, session: SessionDep) -> CheckinDue:
    """Whether to ask "How did last month go?" (once per month, after a few weeks of use)."""
    month, last_day = _previous_month(user_today(user))
    old_enough = user.created_at.date() <= last_day - timedelta(days=MIN_DAYS_IN_MONTH)
    return CheckinDue(
        due=old_enough and not await _checkin_exists(session, user, month), month=month
    )


@router.post("/checkin", response_model=FeedbackRead, status_code=status.HTTP_201_CREATED)
async def send_checkin(body: CheckinIn, user: UserDep, session: SessionDep) -> FeedbackRead:
    today = user_today(user)
    current = f"{today.year:04d}-{today.month:02d}"
    if body.month > current:
        raise DomainValidationError("You can only check in on a month that has started.")
    if await _checkin_exists(session, user, body.month):
        raise ConflictError(f"You already checked in for {body.month}.")
    row = Feedback(
        user_id=user.id, kind=FeedbackKind.CHECKIN, month=body.month, message=body.comment,
        answers=body.model_dump(include={"bills_short", "missed_need_deadline", "followed_plan"}),
    )  # fmt: skip
    session.add(row)
    usage.record(session, user, "checkin", today)
    await session.flush()
    return FeedbackRead.model_validate(row)
