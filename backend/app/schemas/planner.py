from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from app.domain.planner import Action, Reason
from app.models.entities import DeadlineType, ItemKind, ItemStatus, PlanStatus, Tier
from app.schemas.common import ApiModel
from app.schemas.projection import EmergencyIn, ShockIn


class PlanRequest(ApiModel):
    horizon_months: Annotated[int, Field(ge=1, le=24)] = 6
    protect: Annotated[
        list[ShockIn],
        Field(
            default_factory=list, max_length=3, description="Income shocks the plan must survive"
        ),
    ]
    emergencies: Annotated[list[EmergencyIn], Field(default_factory=list, max_length=10)]
    include_postponed: bool = True
    reserve_months: Annotated[int, Field(ge=0, le=24)] | None = None


class DateChange(ApiModel):
    from_: date | None = Field(alias="from")
    to: date | None


class StatusChange(ApiModel):
    from_: ItemStatus = Field(alias="from")
    to: ItemStatus


class ItemChanges(ApiModel):
    target_date: DateChange | None = None
    status: StatusChange | None = None


class DecisionOut(ApiModel):
    item_id: UUID
    item_version: int
    name: str
    tier: Tier
    kind: ItemKind
    priority: int
    quantity: int
    unit_price_minor: int
    cost_minor: int
    current_target_date: date | None
    deadline_type: DeadlineType
    action: Action
    reason: Reason
    period_label: str | None
    pay_on: date | None
    late: bool
    shortfall_minor: int | None
    shortfall_scenario: str | None
    shortfall_on: date | None
    alternative_pay_on: date | None
    max_price_minor: int | None
    requires_reserve_approval: bool
    changes: ItemChanges
    # For reserve decisions: what applying does if the user does not approve using the reserve.
    alternative_changes: ItemChanges | None = None


class ScenarioOut(ApiModel):
    name: str
    min_balance_minor: int
    min_balance_on: date
    first_reserve_breach_on: date | None
    first_negative_on: date | None
    reserve_breached_without_purchases: bool


class PeriodOut(ApiModel):
    index: int
    label: str
    start: date
    end: date
    safe_day: date


class SolverOut(ApiModel):
    status: str
    solve_ms: int
    objective: int


class PlanOut(ApiModel):
    id: UUID
    created_at: datetime
    status: PlanStatus
    stale: bool = False
    horizon_months: int
    currency: str
    reserve_required_minor: int
    planned_spend_minor: int
    summary: str
    summary_source: Literal["mock", "anthropic"]
    summary_notice: str | None
    solver: SolverOut
    scenarios: list[ScenarioOut]
    periods: list[PeriodOut]
    decisions: list[DecisionOut]
    warnings: list[str]


class PlanListItem(ApiModel):
    id: UUID
    created_at: datetime
    status: PlanStatus
    horizon_months: int
    decisions: int
    changes: int


class ApplyRequest(ApiModel):
    item_ids: Annotated[list[UUID], Field(max_length=300)] | None = Field(
        default=None, description="Apply only these items' changes (default: all)"
    )
    allow_reserve: bool = Field(
        default=False, description="Required to apply decisions that dip into the reserve"
    )


class SkippedOut(ApiModel):
    item_id: UUID
    reason: str


class ApplyResponse(ApiModel):
    plan_id: UUID
    status: PlanStatus
    applied: list[UUID]
    skipped: list[SkippedOut]


class ParseItemRequest(ApiModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=500)]


class ItemDraftOut(ApiModel):
    name: str
    tier: Tier
    kind: ItemKind
    priority: int
    estimated_price_minor: int | None
    currency: str
    quantity: int
    target_date: date | None
    deadline_type: DeadlineType
    lead_time_days: int
    location: str | None
    missing: list[str]
    source: Literal["mock", "anthropic"]
    notice: str | None
