from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Self
from uuid import UUID

from pydantic import AnyHttpUrl, Field, StringConstraints, field_validator, model_validator

from app.domain.recurrence import Frequency
from app.models.entities import (
    AccountKind,
    DeadlineType,
    ItemKind,
    ItemStatus,
    PriceSource,
    Tier,
    TxnKind,
)
from app.schemas.common import (
    ApiModel,
    Currency,
    Name,
    NonNegativeMinor,
    PositiveMinor,
    SignedMinor,
)

Category = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
Version = Annotated[int, Field(ge=1, description="Current version for optimistic concurrency")]


def _check_end(anchor: date | None, end: date | None) -> None:
    if anchor is not None and end is not None and end < anchor:
        raise ValueError("end_date must be on or after anchor_date")


# ---------- Accounts ----------
class AccountCreate(ApiModel):
    name: Name
    kind: AccountKind = AccountKind.BANK
    currency: Currency
    opening_balance_minor: SignedMinor = 0
    include_in_planning: bool = True


class AccountUpdate(ApiModel):
    version: Version
    name: Name | None = None
    kind: AccountKind | None = None
    opening_balance_minor: SignedMinor | None = None
    include_in_planning: bool | None = None
    archived: bool | None = None


class AccountRead(ApiModel):
    id: UUID
    name: str
    kind: AccountKind
    currency: str
    opening_balance_minor: int
    balance_minor: int = 0
    include_in_planning: bool
    archived: bool
    version: int
    created_at: datetime
    updated_at: datetime


# ---------- Income ----------
class IncomeCreate(ApiModel):
    name: Name
    amount_minor: PositiveMinor
    currency: Currency
    frequency: Frequency = Frequency.MONTHLY
    anchor_date: date
    end_date: date | None = None
    subject_to_shocks: bool = True
    account_id: UUID | None = None

    @model_validator(mode="after")
    def _dates(self) -> Self:
        _check_end(self.anchor_date, self.end_date)
        return self


class IncomeUpdate(ApiModel):
    version: Version
    name: Name | None = None
    amount_minor: PositiveMinor | None = None
    frequency: Frequency | None = None
    anchor_date: date | None = None
    end_date: date | None = None
    subject_to_shocks: bool | None = None
    account_id: UUID | None = None


class IncomeRead(ApiModel):
    id: UUID
    name: str
    amount_minor: int
    currency: str
    frequency: Frequency
    anchor_date: date
    end_date: date | None
    subject_to_shocks: bool
    account_id: UUID | None
    version: int
    created_at: datetime
    updated_at: datetime


# ---------- Obligations ----------
class ObligationCreate(ApiModel):
    name: Name
    category: Category = "general"
    amount_minor: PositiveMinor
    currency: Currency
    frequency: Frequency = Frequency.MONTHLY
    anchor_date: date
    end_date: date | None = None
    essential: bool = True

    @model_validator(mode="after")
    def _dates(self) -> Self:
        _check_end(self.anchor_date, self.end_date)
        return self


class ObligationUpdate(ApiModel):
    version: Version
    name: Name | None = None
    category: Category | None = None
    amount_minor: PositiveMinor | None = None
    frequency: Frequency | None = None
    anchor_date: date | None = None
    end_date: date | None = None
    essential: bool | None = None


class ObligationRead(ApiModel):
    id: UUID
    name: str
    category: str
    amount_minor: int
    currency: str
    frequency: Frequency
    anchor_date: date
    end_date: date | None
    essential: bool
    version: int
    created_at: datetime
    updated_at: datetime


# ---------- Planned items (needs / wants / desires) ----------
ItemName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Notes = Annotated[str, StringConstraints(max_length=5000)]
Location = Annotated[str, StringConstraints(max_length=200)]


def _http_url(value: AnyHttpUrl | None) -> AnyHttpUrl | None:
    if value is not None and len(str(value)) > 2048:
        raise ValueError("URL is too long")
    return value


class PlannedItemCreate(ApiModel):
    name: ItemName
    tier: Tier
    kind: ItemKind = ItemKind.PRODUCT
    priority: Annotated[int, Field(ge=1, le=5)] = 3
    estimated_price_minor: NonNegativeMinor
    currency: Currency
    quantity: Annotated[int, Field(ge=1, le=1000)] = 1
    target_date: date | None = None
    deadline_type: DeadlineType = DeadlineType.SOFT
    lead_time_days: Annotated[int, Field(ge=0, le=365)] = 0
    max_price_minor: NonNegativeMinor | None = None
    url: AnyHttpUrl | None = None
    location: Location | None = None
    notes: Notes | None = None

    _url = field_validator("url")(_http_url)

    @model_validator(mode="after")
    def _deadline(self) -> Self:
        if self.deadline_type is DeadlineType.HARD and self.target_date is None:
            raise ValueError("A hard deadline requires a target_date")
        return self


class PlannedItemUpdate(ApiModel):
    version: Version
    name: ItemName | None = None
    tier: Tier | None = None
    kind: ItemKind | None = None
    status: ItemStatus | None = None
    priority: Annotated[int, Field(ge=1, le=5)] | None = None
    estimated_price_minor: NonNegativeMinor | None = None
    quantity: Annotated[int, Field(ge=1, le=1000)] | None = None
    target_date: date | None = None
    deadline_type: DeadlineType | None = None
    lead_time_days: Annotated[int, Field(ge=0, le=365)] | None = None
    max_price_minor: NonNegativeMinor | None = None
    url: AnyHttpUrl | None = None
    location: Location | None = None
    notes: Notes | None = None
    purchased_on: date | None = None

    _url = field_validator("url")(_http_url)


class PlannedItemRead(ApiModel):
    id: UUID
    name: str
    tier: Tier
    kind: ItemKind
    status: ItemStatus
    priority: int
    estimated_price_minor: int
    currency: str
    price_source: PriceSource
    price_observed_at: datetime | None
    quantity: int
    target_date: date | None
    deadline_type: DeadlineType
    lead_time_days: int
    max_price_minor: int | None
    url: str | None
    location: str | None
    notes: str | None
    purchased_on: date | None
    version: int
    created_at: datetime
    updated_at: datetime


# ---------- Transactions ----------
class TransactionCreate(ApiModel):
    account_id: UUID
    kind: TxnKind
    amount_minor: PositiveMinor
    occurred_on: date
    category: Category = "general"
    description: Annotated[str, StringConstraints(max_length=500)] | None = None
    planned_item_id: UUID | None = None


class TransactionUpdate(ApiModel):
    version: Version
    kind: TxnKind | None = None
    amount_minor: PositiveMinor | None = None
    occurred_on: date | None = None
    category: Category | None = None
    description: Annotated[str, StringConstraints(max_length=500)] | None = None


class TransactionRead(ApiModel):
    id: UUID
    account_id: UUID
    kind: TxnKind
    amount_minor: int
    currency: str
    occurred_on: date
    category: str
    description: str | None
    planned_item_id: UUID | None
    version: int
    created_at: datetime
    updated_at: datetime
