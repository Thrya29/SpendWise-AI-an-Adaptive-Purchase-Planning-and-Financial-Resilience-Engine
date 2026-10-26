"""Money reminders (in the app, and optionally a daily email digest).

Once per local day, after the morning hour, each user gets reminders that need action:

* an essential bill due in the next few days that the balance cannot cover;
* a planned purchase whose pay day is today;
* yesterday's salary: did it arrive? If not, the planner can replan for a delay.

All numbers come from the cash-flow engine. A dedupe key per reminder means re-running the
check never creates the same reminder twice.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.formatting import format_amount
from app.core import mailer
from app.core.config import get_settings
from app.domain.cashflow import EventKind, ReservePolicy, project
from app.domain.recurrence import Frequency, occurrences
from app.models.entities import (
    Alert,
    AlertKind,
    IncomeStream,
    ItemStatus,
    PlannedItem,
    User,
)
from app.services.ledger import load_planning_inputs

logger = logging.getLogger(__name__)

BILL_LOOKAHEAD_DAYS = 3
DIGEST_MAX_AGE = timedelta(days=3)
RETRY_AFTER_FAILURE = timedelta(hours=1)


def _human(day: date) -> str:
    return f"{day.day} {day.strftime('%b')}"


def local_now(user: User, now: datetime) -> datetime:
    try:
        return now.astimezone(ZoneInfo(user.timezone))
    except (KeyError, ValueError):  # pragma: no cover - timezone is validated on input
        return now


async def _bill_shortfalls(session: AsyncSession, user: User, today: date) -> list[Alert]:
    inputs = await load_planning_inputs(session, user, today)
    proj = project(
        opening_balance=inputs.opening_balance,
        start=today,
        end=today + timedelta(days=BILL_LOOKAHEAD_DAYS),
        incomes=inputs.incomes,
        obligations=inputs.obligations,
        planned=inputs.planned,
        reserve=ReservePolicy(user.reserve_months, user.reserve_buffer_minor),
    )
    essential = {o.name for o in inputs.obligations if o.essential}
    cur = inputs.currency
    out: list[Alert] = []
    for ev in proj.events:
        if (
            ev.kind is not EventKind.OBLIGATION
            or ev.label not in essential
            or ev.balance_after >= 0
        ):
            continue
        short = format_amount(-ev.balance_after, cur)
        out.append(
            Alert(
                user_id=user.id,
                kind=AlertKind.BILL_SHORTFALL,
                title=f"{short} short for {ev.label} on {_human(ev.on)}",
                body=(
                    f"{ev.label} ({format_amount(-ev.amount, cur)}) is due on {_human(ev.on)} and "
                    f"your balance would fall to -{short}. Move money in, or postpone a planned "
                    "purchase and run the planner again."
                ),
                dedupe_key=f"bill:{ev.label}:{ev.on.isoformat()}"[:160],
            )
        )
    return out


async def _buy_days(session: AsyncSession, user: User, today: date) -> list[Alert]:
    items = await session.scalars(
        select(PlannedItem).where(
            PlannedItem.user_id == user.id,
            PlannedItem.status == ItemStatus.PLANNED,
            PlannedItem.target_date.is_not(None),
        )
    )
    out: list[Alert] = []
    for it in items:
        assert it.target_date is not None
        if it.target_date - timedelta(days=it.lead_time_days) != today:
            continue
        total = format_amount(it.estimated_price_minor * it.quantity, it.currency)
        out.append(
            Alert(
                user_id=user.id,
                item_id=it.id,
                kind=AlertKind.BUY_DAY,
                title=f"Today is the planned day to buy {it.name}",
                body=(
                    f"Your plan pays {total} for {it.name} today. Mark it purchased when it's "
                    "done, or run the planner again if something has changed."
                ),
                dedupe_key=f"buy:{it.id}:{today.isoformat()}",
            )
        )
    return out


async def _salary_checks(session: AsyncSession, user: User, today: date) -> list[Alert]:
    yesterday = today - timedelta(days=1)
    incomes = await session.scalars(
        select(IncomeStream).where(
            IncomeStream.user_id == user.id, IncomeStream.subject_to_shocks.is_(True)
        )
    )
    out: list[Alert] = []
    for inc in incomes:
        if inc.frequency is Frequency.ONCE:
            continue
        due = list(occurrences(inc.frequency, inc.anchor_date, yesterday, yesterday, inc.end_date))
        if not due:
            continue
        amount = format_amount(inc.amount_minor, inc.currency)
        out.append(
            Alert(
                user_id=user.id,
                kind=AlertKind.SALARY_CHECK,
                title=f"Did your {inc.name} arrive?",
                body=(
                    f"{inc.name} ({amount}) was due on {_human(yesterday)}. If it's late, open the "
                    "planner, tick 'Salary 1 month late' and run it to see what is still safe."
                ),
                dedupe_key=f"salary:{inc.id}:{yesterday.isoformat()}",
            )
        )
    return out


async def money_alerts(session: AsyncSession, user: User, now: datetime) -> list[Alert]:
    """Create today's reminders for ``user`` if not done yet today. Returns the new alerts."""
    local = local_now(user, now)
    today = local.date()
    if user.money_checked_on == today or local.hour < get_settings().morning_hour:
        return []
    candidates = [
        *await _bill_shortfalls(session, user, today),
        *await _buy_days(session, user, today),
        *await _salary_checks(session, user, today),
    ]
    keys = [a.dedupe_key for a in candidates]
    existing = set(
        await session.scalars(
            select(Alert.dedupe_key).where(Alert.user_id == user.id, Alert.dedupe_key.in_(keys))
        )
    )
    new: list[Alert] = []
    for alert in candidates:
        if alert.dedupe_key in existing:
            continue
        existing.add(alert.dedupe_key)
        alert.created_at = now
        session.add(alert)
        new.append(alert)
    user.money_checked_on = today
    await session.flush()
    return new


def digest_text(user: User, alerts: list[Alert]) -> tuple[str, str]:
    subject = (
        alerts[0].title if len(alerts) == 1 else f"SpendWise: {len(alerts)} things need a look"
    )
    lines = [f"Hi {user.display_name},", ""]
    for a in alerts:
        lines += [f"• {a.title}", f"  {a.body}", ""]
    s = get_settings()
    lines += [
        f"Open SpendWise: {s.app_url.rstrip('/')}/alerts",
        "",
        "You get this because email reminders are on. Turn them off in Settings → Notifications.",
    ]
    return subject, "\n".join(lines)


async def send_digest(session: AsyncSession, user: User, now: datetime) -> bool:
    """Email unread, un-emailed alerts at most once per ``digest_hours``. True if sent."""
    s = get_settings()
    if not (user.email_notifications and mailer.mail_enabled()):
        return False
    if local_now(user, now).hour < s.morning_hour:
        return False
    last = user.last_digest_at
    if last is not None and _aware(last) > now - timedelta(hours=s.digest_hours):
        return False
    pending = list(
        await session.scalars(
            select(Alert)
            .where(
                Alert.user_id == user.id,
                Alert.emailed_at.is_(None),
                Alert.read_at.is_(None),
                Alert.created_at >= now - DIGEST_MAX_AGE,
            )
            .order_by(Alert.created_at)
            .limit(20)
        )
    )
    if not pending:
        return False
    subject, text = digest_text(user, pending)
    try:
        await mailer.send_email(user.email, subject, text)
    except mailer.MailError:
        logger.warning("digest_failed", extra={"user_id": str(user.id)})
        user.last_digest_at = now - timedelta(hours=s.digest_hours) + RETRY_AFTER_FAILURE
        return False
    for a in pending:
        a.emailed_at = now
    user.last_digest_at = now
    return True


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=ZoneInfo("UTC"))
