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
from app.services.fx_service import Converter, latest_table


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
    converter: Converter
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
    """Everything a projection or plan needs, in the user's base currency.

    Other-currency amounts are converted at the latest reference rate and each conversion
    is reported; amounts that cannot be converted are excluded with a warning.
    """
    cur = user.base_currency
    fx = Converter(cur, await latest_table(session, today))
    warnings: list[str] = []

    def to_base(amount: int, currency: str, label: str) -> Money | None:
        converted, note = fx.convert(Money(amount, currency), label)
        if note:
            warnings.append(note)
        return converted

    balances = await account_balances(session, user.id, as_of=today)
    accounts = await session.scalars(
        select(Account).where(
            Account.user_id == user.id, Account.include_in_planning, ~Account.archived
        )
    )
    opening = 0
    for acc in accounts:
        balance = to_base(
            balances.get(acc.id, acc.opening_balance_minor), acc.currency, f"Account '{acc.name}'"
        )
        if balance is not None:
            opening += balance.amount_minor

    inputs = PlanningInputs(
        currency=cur, opening_balance=Money(opening, cur), warnings=warnings, converter=fx
    )

    for inc in await session.scalars(select(IncomeStream).where(IncomeStream.user_id == user.id)):
        amount = to_base(inc.amount_minor, inc.currency, f"Income '{inc.name}'")
        if amount is not None:
            inputs.incomes.append(
                IncomeSpec(
                    inc.name, amount, inc.frequency, inc.anchor_date, inc.end_date,
                    inc.subject_to_shocks,
                )
            )  # fmt: skip

    for ob in await session.scalars(select(Obligation).where(Obligation.user_id == user.id)):
        amount = to_base(ob.amount_minor, ob.currency, f"Obligation '{ob.name}'")
        if amount is not None:
            inputs.obligations.append(
                ObligationSpec(
                    ob.name, amount, ob.frequency, ob.anchor_date, ob.end_date, ob.essential
                )
            )

    if include_planned:
        items = await session.scalars(
            select(PlannedItem).where(
                PlannedItem.user_id == user.id, PlannedItem.status == ItemStatus.PLANNED
            )
        )
        for item in items:
            on = purchase_date(item, today)
            if on is None:
                inputs.unscheduled_items.append(item)
                continue
            total = to_base(
                item.estimated_price_minor * item.quantity, item.currency, f"Item '{item.name}'"
            )
            if total is not None:
                inputs.planned.append(PlannedSpend(str(item.id), item.name, total, on))
        if inputs.unscheduled_items:
            warnings.append(
                f"{len(inputs.unscheduled_items)} planned item(s) have no target date and are "
                "not in this projection. Use the planner to schedule them."
            )
    return inputs
