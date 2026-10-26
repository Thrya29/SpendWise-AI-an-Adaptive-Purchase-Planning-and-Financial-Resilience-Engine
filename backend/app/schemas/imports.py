from __future__ import annotations

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from app.domain.recurrence import Frequency
from app.models.entities import AccountKind
from app.schemas.common import ApiModel, Currency, Name, SignedMinor
from app.schemas.finance import IncomeCreate, ObligationCreate

MAX_STATEMENT_CHARS = 3_000_000  # ~20k rows of a typical export


class StatementIn(ApiModel):
    text: Annotated[str, Field(min_length=1, max_length=MAX_STATEMENT_CHARS)]
    currency: Currency | None = Field(default=None, description="Default: your base currency")
    day_first: bool = Field(default=True, description="Dates like 05/10/2026 are 5 October")


class StatementRowOut(ApiModel):
    on: date
    description: str
    amount_minor: int
    balance_minor: int | None


class RecurringOut(ApiModel):
    key: str
    direction: Literal["income", "expense"]
    name: str
    amount_minor: int
    frequency: Frequency
    last_on: date
    next_on: date
    occurrences: int
    amount_varies: bool
    confidence: Literal["high", "medium"]
    category: str
    essential: bool
    examples: list[str]
    already_set_up: bool = False


class StatementPreviewOut(ApiModel):
    currency: str
    rows: int
    start: date
    end: date
    columns: dict[str, str]
    date_format: str
    skipped_rows: int
    balance_checked: int
    balance_mismatches: int
    opening_balance_minor: int | None
    closing_balance_minor: int | None
    money_in_minor: int
    money_out_minor: int
    recurring: list[RecurringOut]
    recent: list[StatementRowOut]
    warnings: list[str]


class NewAccountIn(ApiModel):
    name: Name
    kind: AccountKind = AccountKind.BANK


class StatementApplyIn(ApiModel):
    account_id: UUID | None = Field(default=None, description="Existing account to update")
    new_account: NewAccountIn | None = None
    currency: Currency | None = None
    closing_balance_minor: SignedMinor | None = Field(
        default=None, description="Set the account so its balance today equals this amount"
    )
    incomes: Annotated[list[IncomeCreate], Field(max_length=20)] = Field(default_factory=list)
    obligations: Annotated[list[ObligationCreate], Field(max_length=60)] = Field(
        default_factory=list
    )


class StatementApplyOut(ApiModel):
    account_id: UUID | None
    balance_minor: int | None
    incomes_created: list[UUID]
    obligations_created: list[UUID]
    skipped: list[str]
