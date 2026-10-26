"""Bank statement import: parse a CSV export and find recurring income and bills.

Pure functions: no I/O, nothing stored. The statement text is parsed in memory and only the
recurring patterns the user confirms become income streams and obligations.

Parsing is layout-agnostic. Indian banks put a preamble (account holder, branch, period)
above the table and name columns differently (``Narration`` / ``Particulars`` /
``Transaction Remarks``; ``Withdrawal Amt.`` / ``Debit`` / ``DR``), so the header row is
found by its contents. When a running balance column exists, every row is checked against
it: a statement that does not add up is reported, never silently trusted.
"""

from __future__ import annotations

import csv
import io
import re
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from itertools import pairwise

from app.domain.money import Money
from app.domain.recurrence import Frequency, add_months

MAX_ROWS = 20_000
HEADER_SCAN_ROWS = 40

# Column roles, each with header patterns in order of preference (matched on normalised text).
_COLUMNS: dict[str, tuple[str, ...]] = {
    "date": (r"^(txn|tran|transaction|posting|post) date$", r"^date$", r"^value (date|dt)$"),
    "description": (
        r"narration", r"particulars", r"transaction remarks", r"^remarks$", r"description",
        r"details",
    ),
    "debit": (r"withdrawal", r"^debit( amount)?( inr)?$", r"^dr$", r"^debits?$"),
    "credit": (r"deposit", r"^credit( amount)?( inr)?$", r"^cr$", r"^credits?$"),
    "amount": (r"^(transaction )?amount( inr)?$", r"^amt$"),
    "direction": (r"^(dr ?cr|cr ?dr|type|debit ?credit|txn type)$",),
    "balance": (r"balance", r"^bal$"),
}  # fmt: skip

_DATE_FORMATS_DAY_FIRST = (
    "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d-%m-%y", "%d.%m.%Y", "%d-%b-%Y", "%d-%b-%y",
    "%d %b %Y", "%d %b %y", "%d %B %Y", "%Y-%m-%d", "%d/%b/%Y",
)  # fmt: skip
_DATE_FORMATS_MONTH_FIRST = ("%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%Y-%m-%d", "%b %d %Y")
_TIME_SUFFIX = re.compile(r"[ T]+\d{1,2}:\d{2}(:\d{2})?( ?[AaPp][Mm])?$")


class StatementError(ValueError):
    """The text could not be read as a bank statement."""


@dataclass(frozen=True, slots=True)
class StatementRow:
    on: date
    description: str
    amount: int  # signed minor units: + money in, - money out
    balance: int | None = None


@dataclass
class ParsedStatement:
    currency: str
    rows: list[StatementRow]
    columns: dict[str, str]  # role -> header as written in the file
    date_format: str
    skipped_rows: int
    balance_checked: int = 0
    balance_mismatches: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def start(self) -> date:
        return self.rows[0].on

    @property
    def end(self) -> date:
        return self.rows[-1].on

    @property
    def closing_balance(self) -> int | None:
        return self.rows[-1].balance

    @property
    def opening_balance(self) -> int | None:
        first = self.rows[0]
        return None if first.balance is None else first.balance - first.amount


def _norm(header: str) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", header.lower()).strip()
    return re.sub(r"\s+", " ", text)


def _match_columns(header: Sequence[str]) -> dict[str, int]:
    found: dict[str, int] = {}
    taken: set[int] = set()
    for role, patterns in _COLUMNS.items():
        for pattern in patterns:
            idx = next(
                (
                    i
                    for i, h in enumerate(header)
                    if i not in taken and re.search(pattern, _norm(h))
                ),
                None,
            )
            if idx is not None:
                found[role] = idx
                taken.add(idx)
                break
    return found


def _usable(cols: dict[str, int]) -> bool:
    return "date" in cols and (("debit" in cols and "credit" in cols) or "amount" in cols)


def _clean_date(cell: str) -> str:
    return _TIME_SUFFIX.sub("", cell.strip())


def _pick_date_format(cells: Sequence[str], day_first: bool) -> str:
    formats = _DATE_FORMATS_DAY_FIRST if day_first else _DATE_FORMATS_MONTH_FIRST
    values = [_clean_date(c) for c in cells if c.strip()]
    best, best_hits = "", 0
    for fmt in formats:
        hits = 0
        for v in values:
            try:
                datetime.strptime(v, fmt)
                hits += 1
            except ValueError:
                pass
        if hits > best_hits:
            best, best_hits = fmt, hits
    if not values or best_hits < 0.8 * len(values):
        raise StatementError("Could not recognise the date format in this statement.")
    return best


def _amount(cell: str, currency: str) -> int | None:
    """Parse '1,23,456.78', '₹ 500', '(250.00)', '1,000.00 Cr', '-75' into minor units."""
    text = cell.strip()
    if text in {"", "-", "--"}:
        return None
    sign = 1
    upper = text.upper()
    if upper.endswith(("CR", "DR")):
        sign = -1 if upper.endswith("DR") else 1
        text = text[:-2]
    if text.startswith("(") and text.endswith(")"):
        sign, text = -sign, text[1:-1]
    text = re.sub(r"(₹|INR|RS\.?|\s|,)", "", text, flags=re.IGNORECASE)
    if text.startswith("-"):
        sign, text = -sign, text[1:]
    elif text.startswith("+"):
        text = text[1:]
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return sign * Money.from_decimal(value, currency).amount_minor


def _direction(cell: str) -> int | None:
    v = cell.strip().lower()
    if v in {"dr", "d", "debit", "withdrawal", "dr."}:
        return -1
    if v in {"cr", "c", "credit", "deposit", "cr."}:
        return 1
    return None


def _find_table(text: str) -> tuple[list[list[str]], int | None, dict[str, int]]:
    """Split into rows and locate the header. Preambles confuse delimiter sniffing, so the
    sniffed delimiter is tried first and the common ones after it."""
    delimiters = [",", "\t", ";", "|"]
    try:
        sniffed = csv.Sniffer().sniff(text[:4096], delimiters="".join(delimiters)).delimiter
        delimiters.remove(sniffed)
        delimiters.insert(0, sniffed)
    except csv.Error:
        pass
    table: list[list[str]] = []
    for delimiter in delimiters:
        table = list(csv.reader(io.StringIO(text), delimiter=delimiter))
        for i, row in enumerate(table[:HEADER_SCAN_ROWS]):
            cols = _match_columns(row)
            if _usable(cols):
                return table, i, cols
    return table, None, {}


def parse_statement(text: str, currency: str, *, day_first: bool = True) -> ParsedStatement:
    if not text.strip():
        raise StatementError("The file is empty.")
    if text.count("\n") > MAX_ROWS + HEADER_SCAN_ROWS:
        raise StatementError(
            f"Statements are limited to {MAX_ROWS:,} rows; export a shorter period."
        )
    table, header_at, cols = _find_table(text)
    if header_at is None:
        raise StatementError(
            "Could not find the transaction table. Expected columns such as Date, "
            "Narration/Description and Withdrawal/Deposit (or Amount)."
        )
    header = table[header_at]
    body = [r for r in table[header_at + 1 :] if any(c.strip() for c in r)]

    def cell(row: Sequence[str], role: str) -> str:
        idx = cols.get(role)
        return row[idx] if idx is not None and idx < len(row) else ""

    date_format = _pick_date_format([cell(r, "date") for r in body], day_first)
    rows: list[StatementRow] = []
    skipped = 0
    for r in body:
        try:
            on = datetime.strptime(_clean_date(cell(r, "date")), date_format).date()
        except ValueError:
            skipped += 1  # footers, totals, page breaks
            continue
        if "debit" in cols and "credit" in cols:
            out_, in_ = _amount(cell(r, "debit"), currency), _amount(cell(r, "credit"), currency)
            amount = (in_ or 0) - abs(out_ or 0) if (in_ or out_) else None
        else:
            raw = _amount(cell(r, "amount"), currency)
            sign = _direction(cell(r, "direction")) if "direction" in cols else None
            amount = None if raw is None else (abs(raw) * sign if sign is not None else raw)
        if not amount:
            skipped += 1
            continue
        balance = _amount(cell(r, "balance"), currency) if "balance" in cols else None
        description = " ".join(cell(r, "description").split()) or "(no description)"
        rows.append(StatementRow(on, description[:200], amount, balance))
    if not rows:
        raise StatementError("No transactions with a date and an amount were found.")

    parsed = ParsedStatement(
        currency=currency,
        rows=_chronological(rows),
        columns={role: header[i].strip() for role, i in cols.items()},
        date_format=date_format,
        skipped_rows=skipped,
    )
    _check_balances(parsed)
    return parsed


def _chronological(rows: list[StatementRow]) -> list[StatementRow]:
    """Oldest first. Many banks list newest first; keep same-day order consistent."""
    if rows[0].on > rows[-1].on:
        rows = rows[::-1]
    return sorted(rows, key=lambda r: r.on)  # stable: same-day order is kept


def _check_balances(parsed: ParsedStatement) -> None:
    checked = mismatches = 0
    for prev, row in pairwise(parsed.rows):
        if prev.balance is not None and row.balance is not None:
            checked += 1
            mismatches += prev.balance + row.amount != row.balance
    if not checked:
        return
    parsed.balance_checked, parsed.balance_mismatches = checked, mismatches
    if mismatches:
        parsed.warnings.append(
            f"{mismatches} of {checked} rows don't add up to the running balance. "
            "Check that the amounts and their signs were read correctly before importing."
        )


# ---- Recurring patterns ------------------------------------------------------------------

_NOISE = re.compile(
    r"\b(upi|imps|neft|rtgs|ach|nach|ecs|pos|mmt|ib|mb|inb|bil|onl|tpt|ft|txn|ref|no|"
    r"transfer|trf|payment|pymt|debit|credit|dr|cr|by|to|from|the|for|ltd|pvt|private|limited|"
    r"india|ind|co|in|a c|ac|acct|account|si|mandate|autopay|chq|cheque|cash|"
    r"jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|month|monthly)\b"
)
_SEPARATORS = re.compile(r"[/\-|:_*#,()]+")  # UPI/NEFT narrations pack fields with these
_DIGITS = re.compile(r"\S*\d\S*")
_HANDLE = re.compile(r"\S+@\S+")

_PERIODS: tuple[tuple[Frequency, int, int, int], ...] = (
    # frequency, min gap, max gap, minimum occurrences
    (Frequency.WEEKLY, 5, 9, 3),
    (Frequency.MONTHLY, 25, 36, 2),
    (Frequency.QUARTERLY, 80, 100, 2),
)

# Keyword -> (suggested name, category, essential). First match wins.
_EXPENSE_HINTS: tuple[tuple[str, str, str, bool], ...] = (
    (r"\brent\b", "Rent", "housing", True),
    (r"\b(emi|loan|lending|finance|bajaj|home ?loan)\b", "Loan EMI", "loan", True),
    (r"\b(electric|electricity|bescom|tneb|msedcl|tata power|adani|power|bses)\b",
     "Electricity", "utilities", True),
    (r"\b(water|gas|lpg|indane|bharat gas|hp gas)\b", "Water and gas", "utilities", True),
    (r"\b(airtel|jio|vodafone|vi|bsnl|act|broadband|fibernet|mobile|recharge)\b",
     "Phone and internet", "utilities", True),
    (r"\b(insurance|lic|premium|policy)\b", "Insurance", "insurance", True),
    (r"\b(school|fees|tuition|college|university)\b", "School fees", "education", True),
    (r"\b(maid|cook|driver|society|maintenance)\b", "Household help", "household", True),
    (r"\b(sip|mutual|groww|zerodha|kuvera|coin)\b", "Investment (SIP)", "savings", False),
    (r"\b(netflix|spotify|prime|hotstar|youtube)\b",
     "Subscription", "subscriptions", False),
    (r"\b(gym|cult|fitness)\b", "Fitness", "health", False),
)  # fmt: skip


@dataclass(frozen=True, slots=True)
class Recurring:
    key: str
    direction: str  # income | expense
    name: str
    amount: int  # typical (median) amount, positive minor units
    frequency: Frequency
    last_on: date
    next_on: date
    occurrences: int
    amount_varies: bool
    confidence: str  # high | medium
    category: str
    essential: bool
    examples: tuple[str, ...]


def description_key(description: str) -> str:
    """A stable key for 'the same payee': references, handles and transfer jargon removed."""
    text = _SEPARATORS.sub(" ", description.lower())
    text = _HANDLE.sub(" ", text)
    text = _DIGITS.sub(" ", text)
    text = re.sub(r"[^a-z ]+", " ", text)
    text = _NOISE.sub(" ", text)
    words = [w for w in text.split() if len(w) >= 3]
    return " ".join(words[:3])


def _period(days: list[date]) -> Frequency | None:
    gaps = [(b - a).days for a, b in pairwise(days)]
    if not gaps:
        return None
    median = statistics.median(gaps)
    for freq, lo, hi, minimum in _PERIODS:
        if lo <= median <= hi and len(days) >= minimum:
            regular = sum(1 for g in gaps if lo <= g <= hi) / len(gaps)
            if regular >= 0.75:
                return freq
    return None


def _next(last: date, freq: Frequency) -> date:
    if freq is Frequency.WEEKLY:
        return last + timedelta(weeks=1)
    return add_months(last, 1 if freq is Frequency.MONTHLY else 3)


def _expense_hint(text: str) -> tuple[str | None, str, bool]:
    for pattern, name, category, essential in _EXPENSE_HINTS:
        if re.search(pattern, text):
            return name, category, essential
    return None, "general", False


def detect_recurring(rows: Sequence[StatementRow]) -> list[Recurring]:
    """Payees seen at a regular weekly, monthly or quarterly rhythm, largest first."""
    groups: dict[tuple[str, str], list[StatementRow]] = {}
    for r in rows:
        key = description_key(r.description)
        if key:
            groups.setdefault(("income" if r.amount > 0 else "expense", key), []).append(r)

    found: list[Recurring] = []
    for (direction, key), members in groups.items():
        # One payment per day at most: same-day splits are summed.
        by_day: dict[date, int] = {}
        for m in members:
            by_day[m.on] = by_day.get(m.on, 0) + abs(m.amount)
        days = sorted(by_day)
        freq = _period(days)
        if freq is None:
            continue
        amounts = [by_day[d] for d in days]
        typical = int(statistics.median(amounts))
        varies = (max(amounts) - min(amounts)) > 0.15 * typical
        text = " ".join(m.description.lower() for m in members)
        if direction == "income":
            is_salary = re.search(r"\b(salary|sal|payroll|wages)\b", text) is not None
            name, category, essential = ("Salary" if is_salary else key.title()), "income", False
        else:
            hint, category, essential = _expense_hint(text)
            name = hint or key.title()
        found.append(
            Recurring(
                key=key,
                direction=direction,
                name=name,
                amount=typical,
                frequency=freq,
                last_on=days[-1],
                next_on=_next(days[-1], freq),
                occurrences=len(days),
                amount_varies=varies,
                confidence="high" if len(days) >= 3 and not varies else "medium",
                category=category,
                essential=essential,
                examples=tuple(dict.fromkeys(m.description for m in members))[:2],
            )
        )
    found.sort(key=lambda r: (r.direction != "income", -r.amount, r.key))
    return found
