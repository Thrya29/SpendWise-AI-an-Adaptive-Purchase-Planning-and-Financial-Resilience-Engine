from datetime import date

from app.domain.recurrence import Frequency, add_months, occurrences


def test_add_months_clamps_month_end() -> None:
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)
    assert add_months(date(2026, 12, 15), 1) == date(2027, 1, 15)
    assert add_months(date(2026, 3, 15), -3) == date(2025, 12, 15)


def test_monthly_keeps_anchor_day_after_short_month() -> None:
    got = list(
        occurrences(Frequency.MONTHLY, date(2026, 1, 31), date(2026, 1, 1), date(2026, 4, 30))
    )
    assert got == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)]


def test_window_and_until() -> None:
    got = list(
        occurrences(
            Frequency.MONTHLY,
            date(2025, 1, 10),
            date(2026, 3, 1),
            date(2026, 12, 31),
            until=date(2026, 5, 10),
        )
    )
    assert got == [date(2026, 3, 10), date(2026, 4, 10), date(2026, 5, 10)]


def test_weekly_alignment_from_old_anchor() -> None:
    got = list(occurrences(Frequency.WEEKLY, date(2026, 1, 5), date(2026, 1, 20), date(2026, 2, 3)))
    assert got == [date(2026, 1, 26), date(2026, 2, 2)]


def test_quarterly_and_yearly() -> None:
    q = list(
        occurrences(Frequency.QUARTERLY, date(2026, 1, 15), date(2026, 1, 1), date(2026, 12, 31))
    )
    assert q == [date(2026, 1, 15), date(2026, 4, 15), date(2026, 7, 15), date(2026, 10, 15)]
    y = list(occurrences(Frequency.YEARLY, date(2024, 2, 29), date(2025, 1, 1), date(2028, 12, 31)))
    assert y == [date(2025, 2, 28), date(2026, 2, 28), date(2027, 2, 28), date(2028, 2, 29)]


def test_once_and_empty_window() -> None:
    assert list(
        occurrences(Frequency.ONCE, date(2026, 5, 1), date(2026, 1, 1), date(2026, 12, 31))
    ) == [date(2026, 5, 1)]
    assert (
        list(occurrences(Frequency.ONCE, date(2027, 5, 1), date(2026, 1, 1), date(2026, 12, 31)))
        == []
    )
    assert (
        list(occurrences(Frequency.MONTHLY, date(2026, 1, 1), date(2026, 5, 1), date(2026, 4, 1)))
        == []
    )
