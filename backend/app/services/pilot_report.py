"""Pilot report for operators: is SpendWise working for real people?

Aggregates only. Setup progress and activity cover users who opted in to usage statistics;
check-ins and comments are what users chose to send. No names, emails or amounts appear.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import (
    Feedback,
    FeedbackKind,
    IncomeStream,
    Obligation,
    Plan,
    PlannedItem,
    PlanStatus,
    UsageEvent,
    User,
)

WEEKS = 8
COMMENTS = 50


def _pct(part: int, whole: int) -> str:
    return "—" if whole == 0 else f"{100 * part / whole:.0f}% ({part}/{whole})"


async def _owners(
    session: AsyncSession, model: type, users: set[UUID], *where: ColumnElement[bool]
) -> int:
    if not users:
        return 0
    rows = await session.scalars(
        select(model.user_id).where(model.user_id.in_(users), *where).distinct()  # type: ignore[attr-defined]
    )
    return len(set(rows))


async def build_report(session: AsyncSession, today: date) -> str:
    total = await session.scalar(select(func.count()).select_from(User)) or 0
    opted = set(await session.scalars(select(User.id).where(User.share_usage.is_(True))))
    events = list(await session.scalars(select(UsageEvent)))
    feedback = list(await session.scalars(select(Feedback).order_by(Feedback.created_at.desc())))

    lines = [
        f"# SpendWise pilot report ({today.isoformat()})",
        "",
        f"* Accounts: {total}; sharing usage statistics: {len(opted)}",
        f"* Check-ins received: {sum(f.kind is FeedbackKind.CHECKIN for f in feedback)}; "
        f"comments: {sum(f.kind is FeedbackKind.COMMENT for f in feedback)}",
        "",
        "## Setup progress (users sharing statistics)",
        "",
        "| Step | Users |",
        "|---|---|",
    ]
    n = len(opted)
    imported = {e.subject for e in events if e.event == "statement_imported"}
    steps = [
        ("Added income", await _owners(session, IncomeStream, opted)),
        ("Added an essential bill", await _owners(session, Obligation, opted,
                                                  Obligation.essential.is_(True))),
        ("Added a need, want or desire", await _owners(session, PlannedItem, opted)),
        ("Ran the planner", await _owners(session, Plan, opted)),
        ("Applied a plan", await _owners(session, Plan, opted, Plan.status == PlanStatus.APPLIED)),
    ]  # fmt: skip
    lines += [f"| {label} | {_pct(count, n)} |" for label, count in steps]
    lines += [f"| Imported a statement | {_pct(len(imported), n)} |", ""]

    lines += ["## Weekly active users", "", "| Week starting | Active |", "|---|---|"]
    monday = today - timedelta(days=today.weekday())
    active_days: dict[str, set[date]] = defaultdict(set)
    for e in events:
        if e.event == "active":
            active_days[e.subject].add(e.day)
    for w in range(WEEKS - 1, -1, -1):
        start = monday - timedelta(weeks=w)
        end = start + timedelta(days=7)
        count = sum(any(start <= d < end for d in days) for days in active_days.values())
        lines.append(f"| {start.isoformat()} | {count} |")
    cohort = [days for days in active_days.values() if min(days) <= today - timedelta(days=35)]
    retained = sum(
        any(min(days) + timedelta(days=22) <= d <= min(days) + timedelta(days=35) for d in days)
        for days in cohort
    )
    lines += [
        "",
        f"Still active in their 4th or 5th week: {_pct(retained, len(cohort))} "
        "(users who started at least 5 weeks ago).",
        "",
        "## Monthly check-ins",
        "",
        "| Month | Answers | Ran short for a bill | Missed a need's deadline | Followed the plan "
        "(mostly / partly / no / no plan) |",
        "|---|---|---|---|---|",
    ]
    by_month: dict[str, list[Feedback]] = defaultdict(list)
    for f in feedback:
        if f.kind is FeedbackKind.CHECKIN and f.month and f.answers:
            by_month[f.month].append(f)
    for month in sorted(by_month, reverse=True):
        rows = by_month[month]
        k = len(rows)
        short = sum(bool(r.answers and r.answers.get("bills_short")) for r in rows)
        missed = sum(bool(r.answers and r.answers.get("missed_need_deadline")) for r in rows)
        follow = Counter(str(r.answers.get("followed_plan")) for r in rows if r.answers)
        split = " / ".join(str(follow.get(x, 0)) for x in ("mostly", "partly", "no", "no_plan"))
        lines.append(f"| {month} | {k} | {_pct(short, k)} | {_pct(missed, k)} | {split} |")
    if not by_month:
        lines.append("| — | 0 | — | — | — |")

    lines += ["", "## Latest comments", ""]
    comments = [f for f in feedback if f.message][:COMMENTS]
    for f in comments:
        rating = f" · {f.rating}/5" if f.rating else ""
        where = f" · {f.page}" if f.page else ""
        kind = " · check-in" if f.kind is FeedbackKind.CHECKIN else ""
        text = " ".join((f.message or "").split())
        lines.append(f"* {f.created_at.date().isoformat()}{rating}{where}{kind}: {text}")
    if not comments:
        lines.append("No comments yet.")
    return "\n".join(lines) + "\n"
