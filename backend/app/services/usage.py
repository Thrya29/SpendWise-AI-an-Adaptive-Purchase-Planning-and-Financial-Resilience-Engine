"""Opt-in, pseudonymous usage statistics.

Nothing is recorded unless the user turned on "Help improve SpendWise". Events carry a keyed
hash instead of the user id, a calendar day (no time), and at most a small count. Never
amounts, names, descriptions or anything typed by the user.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import date
from typing import Literal
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.entities import UsageEvent, User

Event = Literal[
    "active",
    "statement_imported",
    "plan_created",
    "plan_applied",
    "on_time_chosen",
    "checkin",
    "feedback",
]


def subject(user_id: UUID) -> str:
    key = get_settings().encryption_key.encode()
    return hmac.new(key, str(user_id).encode(), hashlib.sha256).hexdigest()[:32]


def record(
    session: AsyncSession, user: User, event: Event, today: date, value: int | None = None
) -> None:
    if user.share_usage:
        session.add(UsageEvent(subject=subject(user.id), event=event, day=today, value=value))


def mark_active(session: AsyncSession, user: User, today: date) -> None:
    """One 'active' event per opted-in user per local day."""
    if user.share_usage and user.last_active_on != today:
        user.last_active_on = today
        record(session, user, "active", today)


async def forget(session: AsyncSession, user_id: UUID) -> None:
    """Erase a user's events (account deletion, or turning sharing off)."""
    await session.execute(delete(UsageEvent).where(UsageEvent.subject == subject(user_id)))
