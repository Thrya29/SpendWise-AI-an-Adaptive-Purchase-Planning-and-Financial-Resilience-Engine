from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import ColumnElement
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import user_today
from app.api.routes.crud import build_crud_router
from app.core.errors import DomainValidationError, NotFoundError
from app.models.entities import (
    Account,
    DeadlineType,
    IncomeStream,
    ItemKind,
    ItemStatus,
    Obligation,
    PlannedItem,
    PriceSource,
    Tier,
    Transaction,
    User,
)
from app.schemas.finance import (
    AccountCreate,
    AccountRead,
    AccountUpdate,
    IncomeCreate,
    IncomeRead,
    IncomeUpdate,
    ObligationCreate,
    ObligationRead,
    ObligationUpdate,
    PlannedItemCreate,
    PlannedItemRead,
    PlannedItemUpdate,
    TransactionCreate,
    TransactionRead,
    TransactionUpdate,
)
from app.services.ledger import account_balances
from app.services.repository import OwnedRepository


async def _owned_account(session: AsyncSession, user: User, account_id: UUID) -> Account:
    try:
        return await OwnedRepository(session, Account, user.id).get(account_id)
    except NotFoundError as exc:
        raise DomainValidationError("account_id does not refer to one of your accounts") from exc


def _check_dates(values: dict[str, Any], current: Any | None) -> None:
    anchor = values.get("anchor_date", getattr(current, "anchor_date", None))
    end = values.get("end_date", getattr(current, "end_date", None))
    if anchor is not None and end is not None and end < anchor:
        raise DomainValidationError("end_date must be on or after anchor_date")


# ---------- Accounts ----------
async def _serialize_accounts(
    session: AsyncSession, user: User, rows: Sequence[Any]
) -> list[BaseModel]:
    balances = await account_balances(session, user.id, as_of=user_today(user))
    out: list[BaseModel] = []
    for row in rows:
        read = AccountRead.model_validate(row)
        read.balance_minor = balances.get(row.id, row.opening_balance_minor)
        out.append(read)
    return out


accounts_router = build_crud_router(
    name="accounts", tag="accounts", model=Account,
    create_schema=AccountCreate, update_schema=AccountUpdate, read_schema=AccountRead,
    order_by=lambda: (Account.archived, Account.name),
    serialize=_serialize_accounts,
    non_nullable=frozenset({"name", "kind", "opening_balance_minor", "include_in_planning",
                            "archived"}),
)  # fmt: skip


# ---------- Income ----------
async def _income_hook(
    session: AsyncSession, user: User, values: dict[str, Any], current: Any | None
) -> dict[str, Any]:
    _check_dates(values, current)
    if values.get("account_id") is not None:
        await _owned_account(session, user, values["account_id"])
    return values


incomes_router = build_crud_router(
    name="incomes", tag="income", model=IncomeStream,
    create_schema=IncomeCreate, update_schema=IncomeUpdate, read_schema=IncomeRead,
    order_by=lambda: (IncomeStream.anchor_date, IncomeStream.name),
    before_write=_income_hook,
    non_nullable=frozenset({"name", "amount_minor", "frequency", "anchor_date",
                            "subject_to_shocks"}),
)  # fmt: skip


# ---------- Obligations ----------
async def _obligation_hook(
    _session: AsyncSession, _user: User, values: dict[str, Any], current: Any | None
) -> dict[str, Any]:
    _check_dates(values, current)
    return values


obligations_router = build_crud_router(
    name="obligations", tag="obligations", model=Obligation,
    create_schema=ObligationCreate, update_schema=ObligationUpdate, read_schema=ObligationRead,
    order_by=lambda: (Obligation.essential.desc(), Obligation.name),
    before_write=_obligation_hook,
    non_nullable=frozenset({"name", "category", "amount_minor", "frequency", "anchor_date",
                            "essential"}),
)  # fmt: skip


# ---------- Planned items ----------
def _item_filters(
    tier: Annotated[Tier | None, Query()] = None,
    status: Annotated[ItemStatus | None, Query()] = None,
    kind: Annotated[ItemKind | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> Sequence[ColumnElement[bool]]:
    out: list[ColumnElement[bool]] = []
    if tier is not None:
        out.append(PlannedItem.tier == tier)
    if status is not None:
        out.append(PlannedItem.status == status)
    if kind is not None:
        out.append(PlannedItem.kind == kind)
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        out.append(PlannedItem.name.ilike(f"%{escaped}%", escape="\\"))
    return out


async def _item_hook(
    _session: AsyncSession, user: User, values: dict[str, Any], current: Any | None
) -> dict[str, Any]:
    if "url" in values and values["url"] is not None:
        values["url"] = str(values["url"])
    if current is None:
        values.setdefault("price_source", PriceSource.USER)
    elif "estimated_price_minor" in values:
        values["price_source"] = PriceSource.USER
        values["price_observed_at"] = None

    deadline = values.get("deadline_type", getattr(current, "deadline_type", None))
    target = (
        values["target_date"] if "target_date" in values else getattr(current, "target_date", None)
    )
    if deadline is DeadlineType.HARD and target is None:
        raise DomainValidationError("A hard deadline requires a target_date")

    status = values.get("status")
    if status is ItemStatus.PURCHASED and values.get("purchased_on") is None:
        values["purchased_on"] = getattr(current, "purchased_on", None) or user_today(user)
    elif status is not None and status is not ItemStatus.PURCHASED:
        values["purchased_on"] = None
    return values


items_router = build_crud_router(
    name="items", tag="planned items", model=PlannedItem,
    create_schema=PlannedItemCreate, update_schema=PlannedItemUpdate, read_schema=PlannedItemRead,
    filters_dep=_item_filters,
    order_by=lambda: (PlannedItem.priority.desc(), PlannedItem.target_date.is_(None),
                      PlannedItem.target_date, PlannedItem.name),
    before_write=_item_hook,
    non_nullable=frozenset({"name", "tier", "kind", "status", "priority", "estimated_price_minor",
                            "quantity", "deadline_type", "lead_time_days", "track_price"}),
)  # fmt: skip


# ---------- Transactions ----------
def _txn_filters(
    account_id: Annotated[UUID | None, Query()] = None,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
) -> Sequence[ColumnElement[bool]]:
    out: list[ColumnElement[bool]] = []
    if account_id is not None:
        out.append(Transaction.account_id == account_id)
    if date_from is not None:
        out.append(Transaction.occurred_on >= date_from)
    if date_to is not None:
        out.append(Transaction.occurred_on <= date_to)
    return out


async def _txn_hook(
    session: AsyncSession, user: User, values: dict[str, Any], current: Any | None
) -> dict[str, Any]:
    if current is None:
        account = await _owned_account(session, user, values["account_id"])
        values["currency"] = account.currency
        if values.get("planned_item_id") is not None:
            try:
                await OwnedRepository(session, PlannedItem, user.id).get(values["planned_item_id"])
            except NotFoundError as exc:
                raise DomainValidationError("planned_item_id is not one of your items") from exc
    return values


transactions_router = build_crud_router(
    name="transactions", tag="transactions", model=Transaction,
    create_schema=TransactionCreate, update_schema=TransactionUpdate, read_schema=TransactionRead,
    filters_dep=_txn_filters,
    order_by=lambda: (Transaction.occurred_on.desc(), Transaction.created_at.desc()),
    before_write=_txn_hook,
    non_nullable=frozenset({"kind", "amount_minor", "occurred_on", "category"}),
)  # fmt: skip


router = APIRouter()
for sub in (accounts_router, incomes_router, obligations_router, items_router, transactions_router):
    router.include_router(sub)
