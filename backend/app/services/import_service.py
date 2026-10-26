"""Statement import: preview (nothing stored) and apply what the user confirmed."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainValidationError, NotFoundError
from app.domain.recurrence import Frequency
from app.domain.statement import Recurring, StatementError, detect_recurring, parse_statement
from app.models.entities import Account, IncomeStream, Obligation, User
from app.schemas.imports import (
    RecurringOut,
    StatementApplyIn,
    StatementApplyOut,
    StatementIn,
    StatementPreviewOut,
    StatementRowOut,
)
from app.services import usage
from app.services.ledger import account_balances
from app.services.repository import OwnedRepository

RECENT_ROWS = 8


def _close(a: int, b: int) -> bool:
    return abs(a - b) <= 0.05 * max(a, b)


async def _existing(session: AsyncSession, user: User) -> list[tuple[str, int, Frequency]]:
    out: list[tuple[str, int, Frequency]] = []
    for model, direction in ((IncomeStream, "income"), (Obligation, "expense")):
        rows = await session.execute(
            select(model.amount_minor, model.frequency).where(model.user_id == user.id)
        )
        out += [(direction, amount, freq) for amount, freq in rows.all()]
    return out


def _already(r: Recurring, existing: list[tuple[str, int, Frequency]]) -> bool:
    return any(
        d == r.direction and f is r.frequency and _close(a, r.amount) for d, a, f in existing
    )


async def preview(session: AsyncSession, user: User, req: StatementIn) -> StatementPreviewOut:
    currency = req.currency or user.base_currency
    try:
        parsed = parse_statement(req.text, currency, day_first=req.day_first)
    except StatementError as exc:
        raise DomainValidationError(str(exc)) from exc
    existing = await _existing(session, user)
    recurring = [
        RecurringOut(
            key=r.key, direction=r.direction,
            name=r.name, amount_minor=r.amount, frequency=r.frequency, last_on=r.last_on,
            next_on=r.next_on, occurrences=r.occurrences, amount_varies=r.amount_varies,
            confidence=r.confidence,
            category=r.category, essential=r.essential, examples=list(r.examples),
            already_set_up=_already(r, existing),
        )
        for r in detect_recurring(parsed.rows)
    ]  # fmt: skip
    return StatementPreviewOut(
        currency=currency,
        rows=len(parsed.rows),
        start=parsed.start,
        end=parsed.end,
        columns=parsed.columns,
        date_format=parsed.date_format,
        skipped_rows=parsed.skipped_rows,
        balance_checked=parsed.balance_checked,
        balance_mismatches=parsed.balance_mismatches,
        opening_balance_minor=parsed.opening_balance,
        closing_balance_minor=parsed.closing_balance,
        money_in_minor=sum(r.amount for r in parsed.rows if r.amount > 0),
        money_out_minor=-sum(r.amount for r in parsed.rows if r.amount < 0),
        recurring=recurring,
        recent=[
            StatementRowOut(
                on=r.on, description=r.description, amount_minor=r.amount, balance_minor=r.balance
            )
            for r in parsed.rows[-RECENT_ROWS:][::-1]
        ],
        warnings=parsed.warnings,
    )


_NOT_YOURS = "account_id does not refer to one of your accounts"


async def _account(
    session: AsyncSession, user: User, req: StatementApplyIn, currency: str, today: date
) -> tuple[Account | None, int | None]:
    """The account to update or create, and its balance afterwards (if set)."""
    accounts = OwnedRepository(session, Account, user.id)
    if req.new_account is not None:
        account = await accounts.create(
            name=req.new_account.name, kind=req.new_account.kind, currency=currency,
            opening_balance_minor=req.closing_balance_minor or 0, include_in_planning=True,
        )  # fmt: skip
        return account, account.opening_balance_minor
    if req.account_id is None:
        return None, None
    try:
        account = await accounts.get(req.account_id)
    except NotFoundError as exc:
        raise DomainValidationError(_NOT_YOURS) from exc
    if account.currency != currency:
        raise DomainValidationError(
            f"That account is in {account.currency}; the statement is in {currency}."
        )
    if req.closing_balance_minor is None:
        return account, None
    current = (await account_balances(session, user.id, as_of=today))[account.id]
    if delta := req.closing_balance_minor - current:
        await accounts.update(
            account.id,
            account.version,
            {"opening_balance_minor": account.opening_balance_minor + delta},
        )
    return account, req.closing_balance_minor


async def apply(
    session: AsyncSession, user: User, req: StatementApplyIn, today: date
) -> StatementApplyOut:
    if req.account_id is not None and req.new_account is not None:
        raise DomainValidationError("Choose an existing account or a new one, not both.")
    currency = req.currency or user.base_currency
    account, balance = await _account(session, user, req, currency, today)
    accounts = OwnedRepository(session, Account, user.id)

    existing = {
        (n.lower(), a, f)
        for model in (IncomeStream, Obligation)
        for n, a, f in (
            await session.execute(
                select(model.name, model.amount_minor, model.frequency).where(
                    model.user_id == user.id
                )
            )
        ).all()
    }
    skipped: list[str] = []
    incomes: list[UUID] = []
    obligations: list[UUID] = []
    streams: list[tuple[Any, list[UUID], OwnedRepository[Any]]] = [
        (req.incomes, incomes, OwnedRepository(session, IncomeStream, user.id)),
        (req.obligations, obligations, OwnedRepository(session, Obligation, user.id)),
    ]
    for payloads, created, repo in streams:
        for p in payloads:
            if (p.name.lower(), p.amount_minor, p.frequency) in existing:
                skipped.append(f"'{p.name}' is already set up")
                continue
            values = p.model_dump()
            if repo.model is IncomeStream:
                if values.get("account_id") is not None:
                    try:
                        await accounts.get(values["account_id"])
                    except NotFoundError as exc:
                        raise DomainValidationError(_NOT_YOURS) from exc
                elif account is not None:
                    values["account_id"] = account.id
            obj = await repo.create(**values)
            created.append(obj.id)
            existing.add((p.name.lower(), p.amount_minor, p.frequency))
    usage.record(session, user, "statement_imported", today, len(incomes) + len(obligations))
    return StatementApplyOut(
        account_id=account.id if account else None,
        balance_minor=balance,
        incomes_created=incomes,
        obligations_created=obligations,
        skipped=skipped,
    )
