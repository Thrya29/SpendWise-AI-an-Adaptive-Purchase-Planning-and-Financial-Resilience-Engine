"""Deterministic recurrence expansion for income and obligations.

Month-based schedules clamp to the last day of short months (e.g. the 31st
becomes 28/29 Feb) while keeping the original anchor day for later months.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterator
from datetime import date, timedelta
from enum import StrEnum


class Frequency(StrEnum):
    ONCE = "once"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


_MONTH_STEP: dict[Frequency, int] = {
    Frequency.MONTHLY: 1,
    Frequency.QUARTERLY: 3,
    Frequency.YEARLY: 12,
}

MAX_OCCURRENCES = 10_000


def add_months(anchor: date, months: int, anchor_day: int | None = None) -> date:
    day = anchor_day if anchor_day is not None else anchor.day
    total = anchor.year * 12 + (anchor.month - 1) + months
    year, month_index = divmod(total, 12)
    month = month_index + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last_day))


def occurrences(
    frequency: Frequency,
    anchor: date,
    start: date,
    end: date,
    until: date | None = None,
) -> Iterator[date]:
    """Yield occurrence dates within [start, end] (inclusive), honouring an optional end date."""
    if end < start:
        return
    stop = min(end, until) if until is not None else end

    if frequency is Frequency.ONCE:
        if start <= anchor <= stop:
            yield anchor
        return

    if frequency is Frequency.WEEKLY:
        current = anchor
        if current < start:
            weeks_behind = (start - current).days // 7
            current += timedelta(weeks=weeks_behind)
            if current < start:
                current += timedelta(weeks=1)
        count = 0
        while current <= stop and count < MAX_OCCURRENCES:
            yield current
            current += timedelta(weeks=1)
            count += 1
        return

    step = _MONTH_STEP[frequency]
    n = 0
    if anchor < start:
        months_behind = (start.year - anchor.year) * 12 + (start.month - anchor.month)
        n = max(0, months_behind // step - 1)
    count = 0
    while count < MAX_OCCURRENCES:
        current = add_months(anchor, n * step, anchor.day)
        if current > stop:
            return
        if current >= start:
            yield current
            count += 1
        n += 1
