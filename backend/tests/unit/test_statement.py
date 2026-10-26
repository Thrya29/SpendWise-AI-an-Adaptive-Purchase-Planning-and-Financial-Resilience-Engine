"""Statement parsing and recurring detection.

Fixtures are synthetic statements for one made-up household (no real account data), written
in layouts modelled on common Indian bank exports.
"""

from datetime import date
from pathlib import Path

import pytest

from app.domain.recurrence import Frequency
from app.domain.statement import (
    StatementError,
    StatementRow,
    _amount,
    description_key,
    detect_recurring,
    parse_statement,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "statements"
LAYOUTS = ["hdfc_style.csv", "sbi_style.txt", "icici_style.csv", "generic_drcr.csv"]


def load(name: str):
    return parse_statement((FIXTURES / name).read_text(encoding="utf-8"), "INR")


@pytest.mark.parametrize("name", LAYOUTS)
def test_every_layout_reads_the_same_transactions(name: str) -> None:
    p = load(name)
    reference = load("hdfc_style.csv")
    assert [(r.on, r.amount) for r in p.rows] == [(r.on, r.amount) for r in reference.rows]
    assert (p.start, p.end, len(p.rows)) == (date(2026, 6, 1), date(2026, 9, 30), 80)
    assert (p.opening_balance, p.closing_balance) == (42_500_00, 112_642_93)
    assert p.balance_checked == 79 and p.balance_mismatches == 0 and not p.warnings


def test_columns_and_footer_rows_are_reported() -> None:
    p = load("hdfc_style.csv")
    assert p.columns["description"] == "Narration" and p.columns["debit"] == "Withdrawal Amt."
    assert p.date_format == "%d/%m/%y" and p.skipped_rows == 2  # summary lines below the table
    assert load("sbi_style.txt").date_format == "%d %b %Y"


def test_wrong_signs_are_caught_by_the_balance_check() -> None:
    # The rent is written without a minus sign, so the running balance disagrees with it.
    text = (
        "Date,Description,Amount,Balance\n"
        "01/10/2026,Salary,50000,50000\n02/10/2026,Rent,20000,30000\n"
    )
    p = parse_statement(text, "INR")
    assert p.balance_mismatches == 1 and "don't add up" in p.warnings[0]


@pytest.mark.parametrize(
    ("cell", "minor"),
    [("1,23,456.78", 12_345_678), ("₹ 500", 50_000), ("(250.00)", -25_000),
     ("1,000.00 Cr", 100_000), ("75.5 Dr", -7_550), ("-75", -7_500), ("Rs. 99", 9_900),
     ("", None), ("-", None), ("n/a", None), ("0.00", 0)],
)  # fmt: skip
def test_amount_cells(cell: str, minor: int | None) -> None:
    assert _amount(cell, "INR") == minor


def test_day_first_by_default_and_month_first_on_request() -> None:
    text = "Date,Description,Amount\n05/10/2026,A,-1\n06/10/2026,B,-1\n"
    assert parse_statement(text, "INR").rows[0].on == date(2026, 10, 5)
    assert parse_statement(text, "INR", day_first=False).rows[0].on == date(2026, 5, 10)
    with_time = "Date,Description,Amount\n05/10/2026 10:15:00,A,-1\n"
    assert parse_statement(with_time, "INR").rows[0].on == date(2026, 10, 5)


@pytest.mark.parametrize(
    ("text", "message"),
    [("", "empty"), ("just,some,words\n1,2,3\n", "transaction table"),
     ("Date,Description,Amount\nsoon,A,1\nlater,B,2\n", "date format"),
     ("Date,Description,Amount\n01/10/2026,A,\n", "No transactions")],
)  # fmt: skip
def test_unreadable_statements_explain_why(text: str, message: str) -> None:
    with pytest.raises(StatementError, match=message):
        parse_statement(text, "INR")


def test_description_key_drops_references_handles_and_months() -> None:
    a = "UPI-RAJESH KUMAR-rajesh.k@okicici-ICIC0001234-610623456789-RENT JUN"
    b = "UPI-RAJESH KUMAR-rajesh.k@okicici-ICIC0001234-610723456789-RENT JUL"
    assert description_key(a) == description_key(b) == "rajesh kumar rent"
    assert description_key("NEFT CR-HDFC0000123-ACME TECHNOLOGIES PVT LTD-SALARY JUN 2026") == (
        "acme technologies salary"
    )
    assert description_key("123456 / 789") == ""


def test_recurring_income_and_bills_are_found_and_irregular_spending_is_not() -> None:
    found = {r.name: r for r in detect_recurring(load("sbi_style.txt").rows)}
    assert set(found) == {
        "Salary", "Rent", "Insurance", "Investment (SIP)", "Electricity", "Household help",
        "Subscription",
    }  # fmt: skip
    salary, rent, maid = found["Salary"], found["Rent"], found["Household help"]
    assert (salary.direction, salary.amount, salary.frequency) == (
        "income",
        85_000_00,
        Frequency.MONTHLY,
    )
    assert salary.next_on == date(2026, 10, 1) and salary.confidence == "high"
    assert (rent.amount, rent.essential, rent.category, rent.next_on) == (
        25_000_00, True, "housing", date(2026, 10, 5))  # fmt: skip
    assert maid.frequency is Frequency.WEEKLY and maid.occurrences == 17
    assert found["Insurance"].frequency is Frequency.QUARTERLY
    assert found["Electricity"].amount_varies and found["Electricity"].confidence == "medium"
    assert not found["Subscription"].essential and not found["Investment (SIP)"].essential


def test_a_single_payment_or_an_irregular_payee_is_not_recurring() -> None:
    rows = [StatementRow(date(2026, 1, d), "UPI-DMART-PAY", -1_000) for d in (2, 3, 19, 20, 27)]
    rows.append(StatementRow(date(2026, 1, 5), "UPI-ONE OFF SHOP-PAY", -5_000))
    assert detect_recurring(rows) == []
