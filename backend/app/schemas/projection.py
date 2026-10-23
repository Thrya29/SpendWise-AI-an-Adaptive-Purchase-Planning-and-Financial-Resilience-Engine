from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import Field

from app.domain.cashflow import EventKind, ShockMode
from app.schemas.common import ApiModel, Name, PositiveMinor


class ShockIn(ApiModel):
    months: Annotated[int, Field(ge=1, le=24)]
    starts_on: date | None = Field(default=None, description="Defaults to the projection start")
    mode: ShockMode = ShockMode.DELAYED


class EmergencyIn(ApiModel):
    name: Name = "Emergency"
    amount_minor: PositiveMinor
    on: date | None = Field(default=None, description="Defaults to the projection start")


class ProjectionRequest(ApiModel):
    horizon_months: Annotated[int, Field(ge=1, le=36)] = 6
    start: date | None = None
    shock: ShockIn | None = None
    emergencies: Annotated[list[EmergencyIn], Field(default_factory=list, max_length=20)]
    include_planned: bool = True
    reserve_months: Annotated[int, Field(ge=0, le=24)] | None = None


class CashEventOut(ApiModel):
    on: date
    kind: EventKind
    label: str
    amount_minor: int
    balance_after_minor: int
    ref: str | None


class MonthOut(ApiModel):
    month: str
    inflow_minor: int
    essential_outflow_minor: int
    discretionary_outflow_minor: int
    planned_outflow_minor: int
    emergency_outflow_minor: int
    closing_balance_minor: int
    min_balance_minor: int


class PlannedCheckOut(ApiModel):
    item_id: str
    name: str
    on: date
    amount_minor: int
    balance_after_minor: int
    keeps_reserve: bool
    stays_solvent: bool


class ProjectionResponse(ApiModel):
    currency: str
    start: date
    end: date
    opening_balance_minor: int
    closing_balance_minor: int
    monthly_essentials_minor: int
    reserve_required_minor: int
    min_balance_minor: int
    min_balance_on: date
    first_reserve_breach_on: date | None
    first_negative_on: date | None
    runway_months: Decimal | None
    is_safe: bool
    months: list[MonthOut]
    events: list[CashEventOut]
    planned_checks: list[PlannedCheckOut]
    warnings: list[str]
