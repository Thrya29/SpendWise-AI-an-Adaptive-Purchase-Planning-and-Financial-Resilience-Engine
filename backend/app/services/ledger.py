"""Account balances and assembly of domain inputs from persisted data."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.cashflow import IncomeSpec, ObligationSpec, PlannedSpend
from app.domain.money import Money
from app.models.entities import (
    Account,
    IncomeStream,
    ItemStatus,
    Obligation,
    PlannedItem,
    Transaction,
    TxnKind,
    User,
)


async def account_balances(
    session: AsyncSession, user_id: UUID, as_of: date | None = None
) -> dict[UUID, int]:
    """Opening balance plus signed transactions up to ``as_of`` (inclusive) per account."""
    signed = case(
        (Transaction.kind == TxnKind.INCOME, Transaction.amount_minor),
        else_=-Transaction.amount_minor,
    )
    query = select(Transaction.account_id, func.coalesce(func.sum(signed), 0)).where(
        Transaction.user_id == user_id
    )
    if as_of is not None:
        query = query.where(Transaction.occurred_on <= as_of)
    rows = (await session.execute(query.group_by(Transaction.account_id))).all()
    sums = {account_id: total for account_id, total in rows}
    accounts = await session.scalars(select(Account).where(Account.user_id == user_id))
    return {a.id: a.opening_balance_minor + int(sums.get(a.id, 0)) for a in accounts}


@dataclass
class PlanningInputs:
    currency: str
    opening_balance: Money
    incomes: list[IncomeSpec] = field(default_factory=list)
    obligations: list[ObligationSpec] = field(default_factory=list)
    planned: list[PlannedSpend] = field(default_factory=list)
    unscheduled_items: list[PlannedItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def purchase_date(item: PlannedItem, today: date) -> date | None:
    """Latest date to pay so the item arrives by its target date (never in the past)."""
    if item.target_date is None:
        return None
    return max(today, item.target_date - timedelta(days=item.lead_time_days))


async def load_planning_inputs(
    session: AsyncSession, user: User, today: date, *, include_planned: bool = True
) -> PlanningInputs:
    cur = user.base_currency
    warnings: list[str] = []

    balances = await account_balances(session, user.id, as_of=today)
    accounts = await session.scalars(
        select(Account).where(
            Account.user_id == user.id, Account.include_in_planning, ~Account.archived
        )
    )
    opening = 0
    for acc in accounts:
        if acc.currency != cur:
            warnings.append(
                f"Account '{acc.name}' ({acc.currency}) excluded: currency differs from {cur}."
            )
            continue
        opening += balances.get(acc.id, acc.opening_balance_minor)

    inputs = PlanningInputs(currency=cur, opening_balance=Money(opening, cur), warnings=warnings)

    for inc in await session.scalars(select(IncomeStream).where(IncomeStream.user_id == user.id)):
        if inc.currency != cur:
            warnings.append(f"Income '{inc.name}' ({inc.currency}) excluded: currency differs.")
            continue
        inputs.incomes.append(
            IncomeSpec(
                inc.name, Money(inc.amount_minor, cur), inc.frequency, inc.anchor_date,
                inc.end_date, inc.subject_to_shocks,
            )
        )  # fmt: skip

    for ob in await session.scalars(select(Obligation).where(Obligation.user_id == user.id)):
        if ob.currency != cur:
            warnings.append(f"Obligation '{ob.name}' ({ob.currency}) excluded: currency differs.")
            continue
        inputs.obligations.append(
            ObligationSpec(
                ob.name, Money(ob.amount_minor, cur), ob.frequency, ob.anchor_date,
                ob.end_date, ob.essential,
            )
        )  # fmt: skip

    if include_planned:
        items = await session.scalars(
            select(PlannedItem).where(
                PlannedItem.user_id == user.id, PlannedItem.status == ItemStatus.PLANNED
            )
        )
        for item in items:
            if item.currency != cur:
                warnings.append(f"Item '{item.name}' ({item.currency}) excluded: currency differs.")
                continue
            on = purchase_date(item, today)
            if on is None:
                inputs.unscheduled_items.append(item)
                continue
            total = item.estimated_price_minor * item.quantity
            inputs.planned.append(PlannedSpend(str(item.id), item.name, Money(total, cur), on))
        if inputs.unscheduled_items:
            warnings.append(
                f"{len(inputs.unscheduled_items)} planned item(s) have no target date and are "
                "not in this projection. Use the planner to schedule them."
            )
    return inputs
