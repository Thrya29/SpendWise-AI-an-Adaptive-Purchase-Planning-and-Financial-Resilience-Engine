from decimal import Decimal

import pytest

from app.domain.savings import (
    fd_maturity,
    jewellery_bill,
    per_gram_from_ounce,
    premature_payout,
    savings_balance,
)

LAKH = 100_000 * 100  # ₹1,00,000 in paise


def test_fd_quarterly_compounding_matches_bank_formula() -> None:
    # ₹1,00,000 at 7% for 12 months, quarterly: 100000 * (1.0175)^4 = 107,185.90
    assert fd_maturity(LAKH, Decimal("7"), 12) == 10_718_590
    # 5 years at 7%: 10,000,000 x 1.0175^20 = 14,147,781.96 paise -> ₹1,41,477.82
    assert fd_maturity(LAKH, Decimal("7"), 60) == 14_147_782
    # Under 6 months is simple interest: 3 months at 6% -> ₹1,01,500
    assert fd_maturity(LAKH, Decimal("6"), 3) == 10_150_000
    assert fd_maturity(LAKH, Decimal("0"), 24) == LAKH


def test_premature_withdrawal_applies_held_rate_minus_penalty() -> None:
    p = premature_payout(LAKH, Decimal("7.25"), 24, 12, rate_for_held_period_percent=Decimal("6.8"))
    assert p.effective_rate_percent == Decimal("5.8")
    assert p.payout == fd_maturity(LAKH, Decimal("5.8"), 12)
    assert p.interest_lost == fd_maturity(LAKH, Decimal("7.25"), 24) - p.payout > 0
    assert premature_payout(LAKH, Decimal("7"), 12, 0).payout == LAKH
    tiny = premature_payout(LAKH, Decimal("0.5"), 12, 6, penalty_percent=Decimal("1"))
    assert tiny.effective_rate_percent == 0 and tiny.payout == LAKH  # never below zero
    full = premature_payout(LAKH, Decimal("7"), 12, 12, penalty_percent=Decimal(0))
    assert full.interest_lost == 0


def test_savings_account_credits_quarterly() -> None:
    # 2 months: nothing credited yet.
    assert savings_balance(LAKH, Decimal("3"), 2) == LAKH
    # 12 months at 3%, monthly rests credited quarterly: ₹1,03,033.91
    assert savings_balance(LAKH, Decimal("3"), 12) == 10_303_391
    assert savings_balance(LAKH, Decimal("3"), 12) < fd_maturity(LAKH, Decimal("7"), 12)


@pytest.mark.parametrize(
    ("args", "msg"),
    [((0, Decimal(7), 12), "Principal"), ((LAKH, Decimal(7), 0), "Tenure"),
     ((LAKH, Decimal(25), 12), "Rate"), ((LAKH, Decimal(-1), 12), "Rate")],
)  # fmt: skip
def test_validation(args: tuple, msg: str) -> None:
    with pytest.raises(ValueError, match=msg):
        fd_maturity(*args)
    with pytest.raises(ValueError, match="within the tenure"):
        premature_payout(LAKH, Decimal(7), 12, 13)
    with pytest.raises(ValueError, match="negative"):
        premature_payout(LAKH, Decimal(7), 12, 6, penalty_percent=Decimal(-1))


def test_gold_conversion_and_jewellery_bill() -> None:
    # $4,030.60/oz -> per gram: 403060 cents / 31.1034768 = 12,958.84 cents
    assert per_gram_from_ounce(403_060) == 12_959
    bill = jewellery_bill(
        rate_24k_per_gram=7_500_00, weight_grams=Decimal("10"), purity="22K",
        making_percent=Decimal("12"), hallmark_fee=45_00,
    )  # fmt: skip
    gold = Decimal(750_000) * Decimal("0.916") / Decimal("0.999") * 10
    assert bill.gold_value == round(gold)
    assert bill.making_charges == round(gold * Decimal("0.12"))
    assert bill.gst == round((gold * Decimal("1.12")) * Decimal("0.03"))
    assert bill.total == bill.gold_value + bill.making_charges + bill.hallmark_fee + bill.gst
    assert bill.effective_per_gram == round(Decimal(bill.total) / 10)

    per_gram = jewellery_bill(rate_24k_per_gram=7_500_00, weight_grams=Decimal("5"),
                              purity="24K", making_per_gram=500_00)  # fmt: skip
    assert per_gram.gold_value == 3_750_000 and per_gram.making_charges == 250_000
    for bad in ({"purity": "21K", "making_percent": Decimal(1)},
                {"purity": "22K"},
                {"purity": "22K", "making_percent": Decimal(1), "making_per_gram": 1}):  # fmt: skip
        with pytest.raises(ValueError):
            jewellery_bill(rate_24k_per_gram=1, weight_grams=Decimal(1), **bad)
    with pytest.raises(ValueError, match="positive"):
        jewellery_bill(rate_24k_per_gram=0, weight_grams=Decimal(1), purity="22K",
                       making_percent=Decimal(1))  # fmt: skip
