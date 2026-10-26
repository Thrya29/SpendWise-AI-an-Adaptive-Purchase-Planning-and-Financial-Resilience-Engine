"""Built-in, offline assistant: rule-based item parsing and template plan summaries.

Deterministic by design: the same text and date always produce the same draft.
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal

from app.ai.schemas import ParseContext, PlanFacts, RawItemDraft
from app.domain.recurrence import add_months

_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m} | {
    m.lower(): i for i, m in enumerate(calendar.month_abbr) if m
}
_MONTHS["sept"] = 9
_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))
_WEEKDAYS = {d.lower(): i for i, d in enumerate(calendar.day_name)}

_CURRENCY_MARKERS = {
    "₹": "INR", "rs": "INR", "rs.": "INR", "inr": "INR", "rupees": "INR",
    "$": "USD", "usd": "USD", "dollars": "USD", "€": "EUR", "eur": "EUR", "euro": "EUR",
    "£": "GBP", "gbp": "GBP", "pounds": "GBP", "aed": "AED", "dirhams": "AED", "sgd": "SGD",
}  # fmt: skip
_MULTIPLIERS = {
    "k": 1_000, "thousand": 1_000, "l": 100_000, "lac": 100_000, "lakh": 100_000,
    "lakhs": 100_000, "cr": 10_000_000, "crore": 10_000_000, "m": 1_000_000, "million": 1_000_000,
}  # fmt: skip

_AMOUNT_RE = re.compile(
    r"(?P<pre>₹|rs\.?|inr|\$|usd|€|eur|£|gbp|aed|sgd)?\s*"
    r"(?P<num>\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"\s*(?P<mult>k|thousand|lakhs?|lac|l|cr|crore|m|million)?\b"
    r"\s*(?P<post>rupees|rs\b\.?|inr|dollars|usd|euros?|eur|pounds|gbp|aed|dirhams|sgd)?",
    re.IGNORECASE,
)
_PRICE_CUES = re.compile(
    r"(around|about|approx\.?|~|for|budget|costs?|price|under|upto|up to|at)\s*$", re.I
)

_KIND_WORDS: list[tuple[str, tuple[str, ...]]] = [
    ("subscription", ("subscription", "netflix", "spotify", "prime", "membership", "plan renewal")),
    ("travel", ("trip", "flight", "flights", "train", "hotel", "vacation", "holiday", "travel",
                "tour", "visa", "getaway")),
    ("service", ("salon", "haircut", "hair cut", "spa", "massage", "repair", "service", "cleaning",
                 "plumber", "electrician", "doctor", "dentist", "checkup", "check-up", "tuition",
                 "class", "classes", "lesson", "mechanic", "manicure", "facial")),
    ("experience", ("concert", "movie", "show", "dinner", "event", "tickets", "ticket", "festival",
                    "party", "match")),
]  # fmt: skip
_NEED_WORDS = (
    "rent", "medicine", "medical", "doctor", "hospital", "dentist", "insurance", "fees", "school",
    "grocery", "groceries", "repair", "bill", "emi", "loan", "electricity", "for work",
    "work laptop",
    "essential", "surgery", "tyre", "tire", "uniform", "books",
)  # fmt: skip
_DESIRE_WORDS = (
    "vacation", "holiday", "luxury", "designer", "concert", "dream", "gaming", "ps5", "xbox",
    "jewellery", "jewelry", "watch", "upgrade", "fancy", "festival", "getaway", "treat",
)  # fmt: skip


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


_DateRule = Callable[[re.Match[str], date], date | None]
_COUNT_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3}
_UNIT_DAYS = {"day": 1, "week": 7}


def _iso(m: re.Match[str], _today: date) -> date | None:
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def _relative(m: re.Match[str], today: date) -> date:
    n = _COUNT_WORDS.get(m[1]) or int(m[1])
    if m[2] == "month":
        return add_months(today, n)
    return today + timedelta(days=n * _UNIT_DAYS[m[2]])


def _next_weekday(m: re.Match[str], today: date) -> date:
    return today + timedelta(days=(_WEEKDAYS[m[1]] - today.weekday()) % 7 or 7)


def _day_and_month(day: int, month: int, year: str | None, today: date) -> date | None:
    try:
        found = date(int(year) if year else today.year, month, day)
    except ValueError:
        return None
    return found if year or found >= today else date(found.year + 1, month, day)


def _whole_month(m: re.Match[str], today: date) -> date:
    month = _MONTHS[m[1]]
    year = int(m[2]) if m[2] else today.year
    if not m[2] and _month_end(year, month) < today:
        year += 1
    return _month_end(year, month)


# Ordered: the first rule that matches wins, so more specific phrases come first.
_DATE_RULES: list[tuple[re.Pattern[str], _DateRule]] = [
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), _iso),
    (re.compile(r"\bday after tomorrow\b"), lambda _m, t: t + timedelta(days=2)),
    (re.compile(r"\b(today|tonight)\b"), lambda _m, t: t),
    (re.compile(r"\btomorrow\b"), lambda _m, t: t + timedelta(days=1)),
    (re.compile(r"\bin\s+(\d{1,3}|a|an|one|two|three)\s+(day|week|month)s?\b"), _relative),
    (re.compile(r"\bnext\s+week\b"), lambda _m, t: t + timedelta(days=7)),
    (re.compile(r"\b(this\s+)?weekend\b"),
     lambda _m, t: t + timedelta(days=(5 - t.weekday()) % 7 or 7)),
    (re.compile(r"\bend of (the )?month\b"), lambda _m, t: _month_end(t.year, t.month)),
    (re.compile(r"\bnext\s+month\b"), lambda _m, t: add_months(t, 1)),
    (re.compile(r"\bnext\s+year\b"), lambda _m, t: add_months(t, 12)),
    (re.compile(rf"\bnext\s+({'|'.join(_WEEKDAYS)})\b"), _next_weekday),
    (re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH_RE})\b\.?(?:\s+(\d{{4}}))?"),
     lambda m, t: _day_and_month(int(m[1]), _MONTHS[m[2]], m[3], t)),
    (re.compile(rf"\b({_MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(\d{{4}}))?"),
     lambda m, t: _day_and_month(int(m[2]), _MONTHS[m[1]], m[3], t)),
    (re.compile(rf"\b(?:by|in|before|during|for)?\s*({_MONTH_RE})\b(?:\s+(\d{{4}}))?"),
     _whole_month),
]  # fmt: skip


def _parse_date(text: str, today: date) -> tuple[date | None, str | None]:
    """Return (date, matched phrase) using the first matching rule."""
    lowered = text.lower()
    for pattern, rule in _DATE_RULES:
        if (m := pattern.search(lowered)) and (found := rule(m, today)) is not None:
            return found, m[0]
    return None, None


def _parse_amount(text: str, base_currency: str) -> tuple[str | None, str | None, str | None]:
    """Return (decimal string in major units, currency, matched phrase)."""
    best: tuple[int, str, str | None, str] | None = None
    lowered = text.lower()
    for m in _AMOUNT_RE.finditer(text):
        num = m["num"].replace(",", "")
        after = lowered[m.end("num") : m.end("num") + 12]
        if re.match(rf"\s*(?:st|nd|rd|th)?\s*(?:of\s+)?(?:{_MONTH_RE})\b", after):
            continue  # "15 Dec" is a date, not a price
        if (
            re.match(
                r"\s*(x|pcs|pieces|tickets?|pairs?|units?|people|persons|nights?|days?|weeks?|months?|years?)\b",
                after,
            )
            and not m["pre"]
        ):
            continue
        before = lowered[max(0, m.start() - 12) : m.start()]
        if re.search(rf"(?:{_MONTH_RE})\s*$", before) and not m["pre"] and not m["mult"]:
            continue  # "Dec 15"
        score = 0
        marker = (m["pre"] or m["post"] or "").lower()
        marker = {"euros": "euro", "rs": "rs"}.get(marker.rstrip("."), marker)
        currency = _CURRENCY_MARKERS.get(marker)
        score += 3 if currency else 0
        score += 2 if m["mult"] else 0
        score += 2 if _PRICE_CUES.search(lowered[: m.start()]) else 0
        value = Decimal(num) * _MULTIPLIERS.get((m["mult"] or "").lower(), 1)
        score += 1 if value >= 100 else 0
        if len(num.split(".")[0]) == 4 and 1900 <= value <= 2100 and not currency and not m["mult"]:
            continue  # looks like a year
        candidate = (score, format(value.normalize(), "f"), currency, m[0].strip())
        if best is None or candidate[0] > best[0]:
            best = candidate
    if best is None:
        return None, None, None
    return best[1], best[2] or base_currency, best[3]


def _contains_any(text: str, words: tuple[str, ...]) -> bool:
    return any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)


def _clean_name(text: str, remove: list[str]) -> str:
    name = text
    for phrase in remove:
        if phrase:
            name = re.sub(re.escape(phrase), " ", name, count=1, flags=re.IGNORECASE)
    name = re.sub(
        r"\b(i\s+(want|need|would like|wanna|plan)\s+to\s+(buy|get|book|do|go\s+for)|"
        r"i\s+(want|need)|buy(ing)?|get(ting)?|book(ing)?|purchase|planning\s+to|plan\s+to|"
        r"around|about|approx\.?|budget(\s+of)?|costs?|for|by|before|on|in|at|under|upto|up to|"
        r"must[\s-]+have|must|urgent(ly)?|asap|maybe|someday|need|a|an|the|my|some)\b",
        " ",
        name,
        flags=re.IGNORECASE,
    )
    name = re.sub(r"[~,;:!?()\-\u2013]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        name = text.strip()[:200] or "New item"
    return (name[0].upper() + name[1:])[:200]


class MockAssistant:
    name = "mock"

    async def parse_item(self, text: str, ctx: ParseContext) -> RawItemDraft:
        lowered = text.lower()
        amount, currency, amount_phrase = _parse_amount(text, ctx.base_currency)
        target, date_phrase = _parse_date(text, ctx.today)

        kind = next((k for k, words in _KIND_WORDS if _contains_any(lowered, words)), "product")
        if _contains_any(lowered, _NEED_WORDS):
            tier = "need"
        elif _contains_any(lowered, _DESIRE_WORDS):
            tier = "desire"
        else:
            tier = "want"

        if re.search(r"\b(urgent(ly)?|asap|critical|emergency|immediately)\b", lowered):
            priority = 5
        elif re.search(
            r"\b(maybe|someday|some day|nice to have|if possible|eventually)\b", lowered
        ):
            priority = 2
        else:
            priority = 4 if tier == "need" else 3

        if target is None:
            deadline = "none"
        elif re.search(r"\b(must|deadline|no later than|latest by|before|urgent)\b", lowered):
            deadline = "hard"
        else:
            deadline = "soft"

        quantity: int | None = None
        qty_phrase: str | None = None
        if m := re.search(r"\b(\d{1,3})\s*x\b|\bx\s*(\d{1,3})\b", lowered):
            quantity, qty_phrase = int(m[1] or m[2]), m[0]
        elif m := re.search(r"\b(\d{1,3})\s*(tickets?|pairs?|units?|pcs|pieces)\b", lowered):
            quantity = int(m[1])  # keep the noun ("2 tickets") in the name, drop only the count
            qty_phrase = m[1]

        location = None
        if m := re.search(
            r"\b(?:at|from)\s+([A-Z][\w&' ]{1,60}?)"
            r"(?=\s+(?:for|by|on|in|next|around|about|under)\b|[,.]|$)",
            text,
        ):
            location = m[1].strip()

        remove = [p for p in (amount_phrase, date_phrase, location, qty_phrase) if p]
        return RawItemDraft(
            name=_clean_name(text, remove),
            tier=tier,
            kind=kind,
            priority=priority,
            amount=amount,
            currency=currency,
            quantity=quantity,
            target_date=target,
            deadline_type=deadline,
            location=location,
        )

    async def summarize_plan(self, facts: PlanFacts) -> str:
        parts: list[str] = []
        if facts.buy_now:
            parts.append(f"You can safely buy {_join(facts.buy_now)} now.")
        if facts.scheduled:
            parts.append("Scheduled: " + "; ".join(f"{n} on {d}" for n, d in facts.scheduled) + ".")
        if facts.using_reserve:
            parts.append(
                f"{_join(facts.using_reserve)} can only happen on time by using part of your "
                f"emergency reserve. That needs your explicit approval."
            )
        if facts.postponed:
            parts.append(
                "Postponed to keep your reserve safe: "
                + "; ".join(f"{n} (needs {s} more headroom)" for n, s in facts.postponed)
                + "."
            )
        if facts.waiting_for_price:
            parts.append(
                f"Waiting for a price at or below your limit: {_join(facts.waiting_for_price)}."
            )
        if facts.late:
            parts.append(f"Later than you wanted: {_join(facts.late)}.")
        if facts.unsafe_anyway:
            parts.append(
                f"Warning: in {_join(facts.unsafe_anyway)}, your balance falls below your "
                f"{facts.reserve} reserve even if you buy nothing, so optional purchases wait "
                "until it recovers. Consider building savings or trimming recurring expenses."
            )
        if not parts:
            parts.append("There is nothing to plan yet.")
        safe = [n for n in facts.scenario_names if n not in facts.unsafe_anyway]
        if facts.reserve_zero:
            parts.append(
                "You have no emergency reserve set up. Add your rent and essential bills, or "
                "a safety buffer in Settings, so plans protect money for emergencies."
            )
        elif safe:
            if len(safe) == 1:
                where = f"in the scenario checked ({safe[0]})"
            else:
                count = "both" if len(safe) == 2 else f"all {len(safe)}"
                where = f"in {count} scenarios checked ({_join(safe)})"
            buying = facts.buy_now or facts.scheduled or facts.using_reserve
            subject = "Every scheduled purchase keeps your" if buying else "Your"
            verb = "" if buying else " stays"
            parts.append(
                f"{subject} {facts.reserve} reserve{verb} intact {where}"
                + (", except where you approve using it." if facts.using_reserve else ".")
            )
        return " ".join(parts)


def _join(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]
