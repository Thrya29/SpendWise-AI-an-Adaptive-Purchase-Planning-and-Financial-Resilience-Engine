from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AnyHttpUrl, Field, StringConstraints

from app.models.entities import AlertKind, Availability, ObservationMethod
from app.schemas.common import ApiModel, PositiveMinor


class PreviewRequest(ApiModel):
    url: AnyHttpUrl


class PreviewOut(ApiModel):
    url: str
    source_name: str
    title: str | None
    found: bool
    price_minor: int | None
    currency: str | None
    method: ObservationMethod | None
    confidence: Literal["high", "medium", "low"] | None
    availability: Availability
    message: str


class ObservationOut(ApiModel):
    id: UUID
    item_id: UUID
    amount_minor: int
    currency: str
    method: ObservationMethod
    confidence: str
    availability: Availability
    source_name: str
    url: str | None
    page_title: str | None
    note: str | None
    observed_at: datetime


class CheckOut(ApiModel):
    found: bool
    message: str
    observation: ObservationOut | None
    applied_to_item: bool
    item_version: int


class QuoteIn(ApiModel):
    amount_minor: PositiveMinor
    source_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]
    note: Annotated[str, StringConstraints(max_length=300)] | None = None


class ApplyObservationIn(ApiModel):
    version: Annotated[int, Field(ge=1)]


class FxOut(ApiModel):
    available: bool
    base: str
    as_of: date | None
    source: str | None
    rates: dict[str, Decimal] = Field(
        default_factory=dict, description="Units of base currency per one unit of each currency"
    )


class AlertOut(ApiModel):
    id: UUID
    item_id: UUID | None
    kind: AlertKind
    title: str
    body: str
    created_at: datetime
    read_at: datetime | None


class AlertCount(ApiModel):
    unread: int


class ForecastOut(ApiModel):
    available: bool
    reason: str | None
    currency: str
    target_minor: int
    horizon_days: int
    by_date: date
    observations: int
    span_days: int
    probability: float | None = None
    confidence: Literal["high", "medium", "low"] | None = None
    current_minor: int | None = None
    reference_minor: int | None = None
    episodes: int | None = None
    recent_low_minor: int | None = None
    recent_median_minor: int | None = None
    recent_high_minor: int | None = None
    basis: str | None = None


class LinkAlternativeIn(ApiModel):
    other_item_id: UUID


class AlternativeSuggestion(ApiModel):
    name: str
    url: str
    source_name: str
    why: str
    price_text: str | None = None


class AlternativesOut(ApiModel):
    available: bool
    message: str
    suggestions: list[AlternativeSuggestion] = Field(default_factory=list)
    dropped_unverified: int = 0
