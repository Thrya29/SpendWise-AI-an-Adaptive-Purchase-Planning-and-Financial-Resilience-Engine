"""Persistence models. All money columns are BIGINT minor units + ISO currency code."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    false,
)
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin, utcnow
from app.domain.recurrence import Frequency


def _enum(cls: type[StrEnum]) -> Enum:
    return Enum(
        cls, native_enum=False, length=24, validate_strings=True,
        values_callable=lambda e: [m.value for m in e],
    )  # fmt: skip


class LlmMode(StrEnum):
    MOCK = "mock"
    ANTHROPIC = "anthropic"


class AccountKind(StrEnum):
    BANK = "bank"
    CASH = "cash"
    WALLET = "wallet"
    SAVINGS = "savings"
    OTHER = "other"


class Tier(StrEnum):
    NEED = "need"
    WANT = "want"
    DESIRE = "desire"


class ItemKind(StrEnum):
    PRODUCT = "product"
    SERVICE = "service"
    TRAVEL = "travel"
    EXPERIENCE = "experience"
    SUBSCRIPTION = "subscription"
    OTHER = "other"


class DeadlineType(StrEnum):
    HARD = "hard"
    SOFT = "soft"
    NONE = "none"


class ItemStatus(StrEnum):
    PLANNED = "planned"
    PURCHASED = "purchased"
    POSTPONED = "postponed"
    DROPPED = "dropped"


class PriceSource(StrEnum):
    USER = "user"
    LINK = "link"
    ESTIMATE = "estimate"
    QUOTE = "quote"  # a quote the user recorded, e.g. from a local shop


class TxnKind(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"


class Owned:
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )


class Versioned:
    """Optimistic concurrency: stale updates raise StaleDataError (mapped to HTTP 409)."""

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, Any]:  # noqa: N805
        return {"version_id_col": cls.__table__.c.version}  # type: ignore[attr-defined]


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    city: Mapped[str | None] = mapped_column(String(120))
    address: Mapped[str | None] = mapped_column(String(500))
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    reserve_months: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=2)
    reserve_buffer_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    llm_mode: Mapped[LlmMode] = mapped_column(_enum(LlmMode), nullable=False, default=LlmMode.MOCK)
    llm_api_key_encrypted: Mapped[str | None] = mapped_column(Text)
    llm_api_key_hint: Mapped[str | None] = mapped_column(String(8))

    __table_args__ = (
        CheckConstraint("reserve_months >= 0 AND reserve_months <= 24", name="reserve_months"),
        CheckConstraint("reserve_buffer_minor >= 0", name="reserve_buffer"),
    )


class RefreshToken(IdMixin, Owned, Base):
    __tablename__ = "refresh_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    family_id: Mapped[UUID] = mapped_column(Uuid, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Account(IdMixin, TimestampMixin, Owned, Versioned, Base):
    __tablename__ = "accounts"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    kind: Mapped[AccountKind] = mapped_column(_enum(AccountKind), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    opening_balance_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    include_in_planning: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class IncomeStream(IdMixin, TimestampMixin, Owned, Versioned, Base):
    __tablename__ = "income_streams"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    frequency: Mapped[Frequency] = mapped_column(_enum(Frequency), nullable=False)
    anchor_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    subject_to_shocks: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    account_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="SET NULL")
    )

    __table_args__ = (CheckConstraint("amount_minor > 0", name="income_positive"),)


class Obligation(IdMixin, TimestampMixin, Owned, Versioned, Base):
    __tablename__ = "obligations"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="general")
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    frequency: Mapped[Frequency] = mapped_column(_enum(Frequency), nullable=False)
    anchor_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    essential: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (CheckConstraint("amount_minor > 0", name="obligation_positive"),)


class PlannedItem(IdMixin, TimestampMixin, Owned, Versioned, Base):
    __tablename__ = "planned_items"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    tier: Mapped[Tier] = mapped_column(_enum(Tier), nullable=False, index=True)
    kind: Mapped[ItemKind] = mapped_column(_enum(ItemKind), nullable=False)
    status: Mapped[ItemStatus] = mapped_column(
        _enum(ItemStatus), nullable=False, default=ItemStatus.PLANNED, index=True
    )
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=3)
    estimated_price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    price_source: Mapped[PriceSource] = mapped_column(
        _enum(PriceSource), nullable=False, default=PriceSource.USER
    )
    price_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quantity: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    target_date: Mapped[date | None] = mapped_column(Date)
    deadline_type: Mapped[DeadlineType] = mapped_column(
        _enum(DeadlineType), nullable=False, default=DeadlineType.SOFT
    )
    lead_time_days: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    max_price_minor: Mapped[int | None] = mapped_column(BigInteger)
    url: Mapped[str | None] = mapped_column(String(2048))
    location: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    purchased_on: Mapped[date | None] = mapped_column(Date)
    track_price: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_check_error: Mapped[str | None] = mapped_column(String(300))
    failed_checks: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )

    __table_args__ = (
        CheckConstraint("priority BETWEEN 1 AND 5", name="priority_range"),
        CheckConstraint("estimated_price_minor >= 0", name="price_non_negative"),
        CheckConstraint("quantity BETWEEN 1 AND 1000", name="quantity_range"),
        CheckConstraint("lead_time_days BETWEEN 0 AND 365", name="lead_time_range"),
    )


class Transaction(IdMixin, TimestampMixin, Owned, Versioned, Base):
    __tablename__ = "transactions"

    account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    kind: Mapped[TxnKind] = mapped_column(_enum(TxnKind), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="general")
    description: Mapped[str | None] = mapped_column(String(500))
    planned_item_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("planned_items.id", ondelete="SET NULL")
    )

    __table_args__ = (CheckConstraint("amount_minor > 0", name="txn_positive"),)


class AuditEvent(IdMixin, Owned, Base):
    __tablename__ = "audit_events"

    entity: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    changes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class PlanStatus(StrEnum):
    DRAFT = "draft"
    APPLIED = "applied"
    DISCARDED = "discarded"


class Plan(IdMixin, Owned, Base):
    """A planner run. Drafts can be applied only while the user's data is unchanged."""

    __tablename__ = "plans"

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    status: Mapped[PlanStatus] = mapped_column(
        _enum(PlanStatus), nullable=False, default=PlanStatus.DRAFT
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    horizon_months: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    request: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ObservationMethod(StrEnum):
    JSON_LD = "json_ld"
    MICRODATA = "microdata"
    OPENGRAPH = "opengraph"
    MANUAL = "manual"


class Availability(StrEnum):
    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    PREORDER = "preorder"
    UNKNOWN = "unknown"


class PriceObservation(IdMixin, Owned, Base):
    """One price seen for an item, with full provenance. Never edited, only appended."""

    __tablename__ = "price_observations"

    item_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("planned_items.id", ondelete="CASCADE"), index=True, nullable=False
    )
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    method: Mapped[ObservationMethod] = mapped_column(_enum(ObservationMethod), nullable=False)
    confidence: Mapped[str] = mapped_column(String(10), nullable=False)
    availability: Mapped[Availability] = mapped_column(
        _enum(Availability), nullable=False, default=Availability.UNKNOWN
    )
    source_name: Mapped[str] = mapped_column(String(200), nullable=False)  # domain or shop
    url: Mapped[str | None] = mapped_column(String(2048))
    page_title: Mapped[str | None] = mapped_column(String(300))
    note: Mapped[str | None] = mapped_column(String(300))
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )

    __table_args__ = (CheckConstraint("amount_minor > 0", name="observation_positive"),)


class FxRate(IdMixin, Base):
    """Reference exchange rate: 1 ``pivot`` = ``rate`` ``currency`` on ``rate_date``."""

    __tablename__ = "fx_rates"

    pivot: Mapped[str] = mapped_column(String(3), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    rate: Mapped[str] = mapped_column(String(40), nullable=False)  # exact decimal string
    rate_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("pivot", "currency", "rate_date", name="uq_fx_rates_pair_day"),
    )


class AlertKind(StrEnum):
    PRICE_TARGET = "price_target"
    PRICE_DROP = "price_drop"
    CHECK_FAILING = "check_failing"
    BACK_IN_STOCK = "back_in_stock"


class Alert(IdMixin, Owned, Base):
    __tablename__ = "alerts"

    item_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("planned_items.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[AlertKind] = mapped_column(_enum(AlertKind), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
