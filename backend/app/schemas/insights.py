from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from app.schemas.common import ApiModel, NonNegativeMinor, PositiveMinor

Rate = Annotated[Decimal, Field(ge=0, le=20, max_digits=6, decimal_places=3)]
EDUCATIONAL = (
    "Educational estimate, not investment advice. Check your bank's or fund's exact terms; "
    "past performance does not guarantee future returns."
)


class SafeToLockOut(ApiModel):
    currency: str
    amount_minor: int
    months: int
    available_now_minor: int
    reserve_minor: int
    monthly_essentials_minor: int
    runway_months: str | None
    binding_scenario: str
    lowest_point_on: date
    explanation: str
    warnings: list[str]
    disclaimer: str = EDUCATIONAL


class PrematureIn(ApiModel):
    held_months: Annotated[int, Field(ge=0, le=120)]
    rate_for_held_period_percent: Rate | None = None
    penalty_percent: Annotated[Decimal, Field(ge=0, le=5)] = Decimal("1.0")


class DepositIn(ApiModel):
    principal_minor: PositiveMinor
    fd_rate_percent: Rate
    months: Annotated[int, Field(ge=1, le=120)]
    savings_rate_percent: Rate = Decimal("2.70")
    premature: PrematureIn | None = None

    @model_validator(mode="after")
    def _held_within_tenure(self) -> Self:
        if self.premature and self.premature.held_months > self.months:
            raise ValueError("held_months cannot exceed the FD tenure")
        return self


class DepositOut(ApiModel):
    currency: str
    fd_maturity_minor: int
    fd_interest_minor: int
    savings_balance_minor: int
    savings_interest_minor: int
    fd_advantage_minor: int
    premature_payout_minor: int | None = None
    premature_effective_rate_percent: Decimal | None = None
    premature_interest_lost_minor: int | None = None
    notes: list[str]
    disclaimer: str = EDUCATIONAL


class SimulateIn(ApiModel):
    initial_minor: NonNegativeMinor = 0
    monthly_minor: NonNegativeMinor = 0
    months: Annotated[int, Field(ge=1, le=480)]
    annual_return_percent: Annotated[Decimal, Field(gt=-50, lt=100)] | None = None
    annual_volatility_percent: Annotated[Decimal, Field(ge=0, lt=150)] | None = None
    scheme_code: int | None = Field(
        default=None, description="Use this fund's historical return and volatility as inputs"
    )
    compare_fd_rate_percent: Rate | None = None


class SimulateOut(ApiModel):
    currency: str
    months: int
    invested_minor: int
    p10_minor: int
    p50_minor: int
    p90_minor: int
    probability_of_loss: float
    median_max_drawdown: float
    annual_return_percent: Decimal
    annual_volatility_percent: Decimal
    assumptions_source: str
    fd_value_minor: int | None
    paths: int
    seed: int
    disclaimer: str = EDUCATIONAL


class FundOut(ApiModel):
    scheme_code: int
    name: str
    fund_house: str | None
    category: str | None
    isin: str | None
    nav: str | None
    nav_date: date | None
    active: bool


class FundDetailOut(FundOut):
    source: str
    history_source: str | None
    history_points: int
    history_from: date | None
    cagr_percent: dict[str, Decimal]
    volatility_percent: Decimal | None
    max_drawdown_percent: Decimal | None
    watched: bool
    disclaimer: str = EDUCATIONAL


class WatchIn(ApiModel):
    scheme_code: int


class GoldOut(ApiModel):
    available: bool
    currency: str
    per_gram_24k_minor: int | None = None
    per_gram_22k_minor: int | None = None
    usd_per_ounce: str | None = None
    observed_at: datetime | None = None
    source: str | None = None
    fx_note: str | None = None
    caveat: str = (
        "International spot price converted at the ECB reference rate. Indian retail rates are "
        "higher: they add import duty, GST and dealer margin. Use your jeweller's quoted rate "
        "for a bill estimate."
    )


class JewelleryIn(ApiModel):
    rate_24k_per_gram_minor: PositiveMinor
    weight_grams: Annotated[Decimal, Field(gt=0, le=10_000, decimal_places=3)]
    purity: Literal["24K", "22K", "18K", "14K"] = "22K"
    making_percent: Annotated[Decimal, Field(ge=0, le=50)] | None = None
    making_per_gram_minor: NonNegativeMinor | None = None
    gst_percent: Annotated[Decimal, Field(ge=0, le=28)] = Decimal(3)
    hallmark_fee_minor: NonNegativeMinor = 0

    @model_validator(mode="after")
    def _one_making_charge(self) -> Self:
        if (self.making_percent is None) == (self.making_per_gram_minor is None):
            raise ValueError("Give making charges either as a percentage or per gram")
        return self


class JewelleryOut(ApiModel):
    currency: str
    gold_value_minor: int
    making_charges_minor: int
    hallmark_fee_minor: int
    gst_minor: int
    total_minor: int
    effective_per_gram_minor: int
