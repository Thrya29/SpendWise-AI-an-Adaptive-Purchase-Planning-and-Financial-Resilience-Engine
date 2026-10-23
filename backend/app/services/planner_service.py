"""Planner orchestration: load data, solve, explain, persist drafts, apply with consent."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import service as ai
from app.ai.formatting import format_amount
from app.ai.schemas import PlanFacts
from app.core.db import utcnow
from app.core.errors import ConflictError, DomainValidationError
from app.domain.cashflow import Emergency, IncomeShock, ReservePolicy, Scenario, ShockMode
from app.domain.money import Money
from app.domain.planner import Action, Decision, NamedScenario, PlanItem, PlanResult, plan_purchases
from app.models.entities import (
    Account,
    IncomeStream,
    ItemStatus,
    Obligation,
    Plan,
    PlannedItem,
    PlanStatus,
    Transaction,
    User,
)
from app.schemas.planner import (
    ApplyRequest,
    ApplyResponse,
    DecisionOut,
    ItemChanges,
    PeriodOut,
    PlanOut,
    PlanRequest,
    ScenarioOut,
    SkippedOut,
    SolverOut,
)
from app.services import forecast_service
from app.services.ledger import load_planning_inputs
from app.services.repository import OwnedRepository

_SCHEDULING = {Action.BUY_NOW, Action.SCHEDULE, Action.USE_RESERVE}


def _shock_name(months: int, mode: ShockMode) -> str:
    unit = "month" if months == 1 else "months"
    if mode is ShockMode.LOST:
        return f"No salary for {months} {unit}"
    return f"Salary delayed {months} {unit}"


def _human_date(day: date) -> str:
    return f"{day.day} {day.strftime('%b %Y')}"


async def fingerprint(session: AsyncSession, user: User, today: date) -> str:
    """Hash of everything a plan depends on; any change makes older drafts stale."""
    parts: dict[str, Any] = {
        "today": today.isoformat(),
        "currency": user.base_currency,
        "reserve": [user.reserve_months, user.reserve_buffer_minor],
    }
    for model in (Account, IncomeStream, Obligation, PlannedItem, Transaction):
        rows = await session.execute(
            select(model.id, model.version).where(model.user_id == user.id).order_by(model.id)
        )
        parts[model.__tablename__] = [[str(i), v] for i, v in rows.all()]
    blob = json.dumps(parts, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def _changes(item: PlannedItem, d: Decision, pay_on: date | None = None) -> ItemChanges:
    changes: dict[str, Any] = {}
    pay_on = pay_on or d.pay_on
    if d.action in _SCHEDULING and pay_on is not None:
        new_target = pay_on + timedelta(days=item.lead_time_days)
        if new_target != item.target_date:
            changes["target_date"] = {"from": item.target_date, "to": new_target}
        if item.status is not ItemStatus.PLANNED:
            changes["status"] = {"from": item.status, "to": ItemStatus.PLANNED}
    elif d.action is Action.POSTPONE and item.status is not ItemStatus.POSTPONED:
        changes["status"] = {"from": item.status, "to": ItemStatus.POSTPONED}
    return ItemChanges.model_validate(changes)


async def _wait_forecast(
    session: AsyncSession, row: PlannedItem, d: Decision, today: date, horizon_months: int
) -> dict[str, Any]:
    """For "wait for a better price": the chance of reaching the limit before it is needed."""
    if d.action is not Action.WAIT_PRICE or row.max_price_minor is None:
        return {}
    horizon = min(forecast_service.default_horizon(row, today), 31 * horizon_months)
    f = await forecast_service.item_forecast(
        session, row, today, target=row.max_price_minor, horizon_days=max(horizon, 1)
    )
    if not f.available:
        return {"forecast_note": f.reason}
    return {
        "forecast_probability": f.probability,
        "forecast_by": f.by_date,
        "forecast_confidence": f.confidence,
    }


def _note_waiting_alternatives(
    decisions: list[DecisionOut], items: dict[str, PlannedItem], today: date
) -> None:
    """Warn when buying a fallback would rule out a preferred alternative that is waiting.

    The solver cannot buy an item above its price limit, so a lower-ranked alternative may be
    scheduled instead. That trade-off is the user's call, so it is stated, not hidden.
    """
    by_id = {str(d.item_id): d for d in decisions}
    for d in decisions:
        if d.action not in _SCHEDULING:
            continue
        group = items[str(d.item_id)].alternative_group
        if group is None:
            continue
        for other in decisions:
            row = items[str(other.item_id)]
            if (
                other.action is Action.WAIT_PRICE
                and row.alternative_group == group
                and row.priority >= d.priority
                and other.forecast_probability is not None
                and other.forecast_by is not None
            ):
                pct = round(other.forecast_probability * 100)
                by_id[str(d.item_id)].group_note = (
                    f"Your preferred {other.name} is waiting for a better price ({pct}% chance "
                    f"by {_human_date(other.forecast_by)}). Buying this now rules it out."
                )
                break


def _facts(
    result: PlanResult,
    items: dict[str, PlannedItem],
    *,
    unit_prices: dict[str, int],
    horizon: int,
    warnings: list[str],
    forecasts: dict[str, float],
) -> PlanFacts:
    cur = result.currency

    def by(*actions: Action) -> list[Decision]:
        return [d for d in result.decisions if d.action in actions]

    def names(decisions: list[Decision]) -> list[str]:
        return [items[d.ref].name for d in decisions]

    planned_total = sum(unit_prices[d.ref] * items[d.ref].quantity for d in by(*_SCHEDULING))
    return PlanFacts(
        currency=cur,
        horizon_months=horizon,
        scenario_names=[o.name for o in result.outcomes],
        buy_now=names(by(Action.BUY_NOW)),
        scheduled=[
            (items[d.ref].name, _human_date(d.pay_on)) for d in by(Action.SCHEDULE) if d.pay_on
        ],
        postponed=[
            (items[d.ref].name, format_amount(d.shortfall or 0, cur)) for d in by(Action.POSTPONE)
        ],
        waiting_for_price=[
            items[d.ref].name
            + (
                f" ({round(forecasts[d.ref] * 100)}% chance of reaching your limit in time)"
                if d.ref in forecasts
                else ""
            )
            for d in by(Action.WAIT_PRICE)
        ],
        using_reserve=names(by(Action.USE_RESERVE)),
        late=names([d for d in result.decisions if d.late]),
        total_planned=format_amount(planned_total, cur),
        reserve=format_amount(result.reserve_required, cur),
        reserve_zero=result.reserve_required == 0,
        lowest_balance=[(o.name, format_amount(o.min_balance, cur)) for o in result.outcomes],
        unsafe_anyway=[o.name for o in result.outcomes if o.reserve_breached_without_purchases],
        warnings=warnings,
    )


async def create_plan(session: AsyncSession, user: User, req: PlanRequest, today: date) -> PlanOut:
    inputs = await load_planning_inputs(session, user, today, include_planned=False)
    cur = inputs.currency
    statuses = [ItemStatus.PLANNED] + ([ItemStatus.POSTPONED] if req.include_postponed else [])
    rows = list(
        await session.scalars(
            select(PlannedItem)
            .where(PlannedItem.user_id == user.id, PlannedItem.status.in_(statuses))
            .order_by(PlannedItem.created_at, PlannedItem.id)
        )
    )
    warnings = list(inputs.warnings)
    items: dict[str, PlannedItem] = {}
    unit_prices: dict[str, int] = {}
    plan_items: list[PlanItem] = []
    for row in rows:
        unit = Money(row.estimated_price_minor, row.currency)
        converted, note = inputs.converter.convert(unit, f"Item '{row.name}'")
        if note:
            warnings.append(note)
        if converted is None:
            continue
        cap = row.max_price_minor
        if cap is not None and row.currency != cur:
            cap_money, _ = inputs.converter.convert(Money(cap, row.currency), "cap")
            cap = cap_money.amount_minor if cap_money else None
        items[str(row.id)] = row
        unit_prices[str(row.id)] = converted.amount_minor
        plan_items.append(
            PlanItem(
                ref=str(row.id), name=row.name, tier=row.tier.value, priority=row.priority,
                unit_price=converted.amount_minor, quantity=row.quantity,
                deadline=row.deadline_type.value, target_date=row.target_date,
                lead_time_days=row.lead_time_days, max_price=cap,
                group=str(row.alternative_group) if row.alternative_group else None,
            )
        )  # fmt: skip
    if len(plan_items) > 300:
        raise DomainValidationError("The planner supports up to 300 active items at once.")

    end_guard = today + timedelta(days=31 * req.horizon_months)
    emergencies: list[Emergency] = []
    for em in req.emergencies:
        on = em.on or today
        if not today <= on <= end_guard:
            raise DomainValidationError(f"Emergency '{em.name}' falls outside the planning window")
        emergencies.append(Emergency(em.name, Money(em.amount_minor, cur), on))

    scenarios = [NamedScenario("As expected", Scenario(emergencies=tuple(emergencies)))]
    for shock in req.protect:
        name = _shock_name(shock.months, shock.mode)
        if any(s.name == name for s in scenarios):
            continue
        scenarios.append(
            NamedScenario(
                name,
                Scenario(
                    shock=IncomeShock(shock.months, shock.starts_on or today, shock.mode),
                    emergencies=tuple(emergencies),
                ),
            )
        )

    reserve = ReservePolicy(
        months_of_essentials=req.reserve_months
        if req.reserve_months is not None
        else user.reserve_months,
        min_buffer=user.reserve_buffer_minor,
    )
    result = await asyncio.to_thread(
        lambda: plan_purchases(
            opening_balance=inputs.opening_balance,
            today=today,
            horizon_months=req.horizon_months,
            items=plan_items,
            incomes=inputs.incomes,
            obligations=inputs.obligations,
            scenarios=scenarios,
            reserve=reserve,
        )
    )
    warnings += result.warnings

    period_label = {p.index: p.label for p in result.periods}
    decisions = []
    for d in result.decisions:
        row = items[d.ref]
        decisions.append(
            DecisionOut(
                item_id=row.id, item_version=row.version, name=row.name, tier=row.tier,
                kind=row.kind, priority=row.priority, quantity=row.quantity,
                unit_price_minor=unit_prices[d.ref],
                cost_minor=unit_prices[d.ref] * row.quantity,
                original_currency=row.currency,
                original_unit_price_minor=row.estimated_price_minor,
                current_target_date=row.target_date, deadline_type=row.deadline_type,
                action=d.action, reason=d.reason,
                period_label=period_label.get(d.period) if d.period is not None else None,
                pay_on=d.pay_on, late=d.late, shortfall_minor=d.shortfall,
                shortfall_scenario=d.shortfall_scenario, shortfall_on=d.shortfall_on,
                alternative_pay_on=d.alternative_pay_on, max_price_minor=row.max_price_minor,
                requires_reserve_approval=d.action is Action.USE_RESERVE,
                changes=_changes(row, d),
                chosen_alternative_id=items[d.chosen_alternative].id
                if d.chosen_alternative
                else None,
                **(await _wait_forecast(session, row, d, today, req.horizon_months)),
                alternative_changes=_changes(row, d, d.alternative_pay_on)
                if d.alternative_pay_on
                else None,
            )
        )  # fmt: skip

    summary = await ai.summarize_plan(
        user,
        _facts(
            result,
            items,
            unit_prices=unit_prices,
            horizon=req.horizon_months,
            warnings=warnings,
            forecasts={
                str(d.item_id): d.forecast_probability
                for d in decisions
                if d.forecast_probability is not None
            },
        ),
    )
    _note_waiting_alternatives(decisions, items, today)
    planned_spend = sum(d.cost_minor for d in decisions if d.action in _SCHEDULING)
    plan = Plan(
        user_id=user.id,
        fingerprint=await fingerprint(session, user, today),
        horizon_months=req.horizon_months,
        request=req.model_dump(mode="json"),
        result={},
    )
    session.add(plan)
    await session.flush()
    out = PlanOut(
        id=plan.id, created_at=plan.created_at, status=PlanStatus.DRAFT,
        horizon_months=req.horizon_months, currency=cur,
        reserve_required_minor=result.reserve_required, planned_spend_minor=planned_spend,
        summary=summary.value, summary_source=summary.source,
        summary_notice=summary.notice,
        solver=SolverOut(status=result.solver_status, solve_ms=result.solve_ms,
                         objective=result.objective),
        scenarios=[ScenarioOut(
            name=o.name, min_balance_minor=o.min_balance, min_balance_on=o.min_balance_on,
            first_reserve_breach_on=o.first_reserve_breach_on,
            first_negative_on=o.first_negative_on,
            reserve_breached_without_purchases=o.reserve_breached_without_purchases,
        ) for o in result.outcomes],
        periods=[PeriodOut(index=p.index, label=p.label, start=p.start, end=p.end, safe_day=s)
                 for p, s in zip(result.periods, result.safe_days, strict=True)],
        decisions=decisions,
        warnings=warnings,
    )  # fmt: skip
    plan.result = out.model_dump(mode="json", by_alias=True)
    return out


async def get_plan(session: AsyncSession, user: User, plan_id: UUID, today: date) -> PlanOut:
    plan = await OwnedRepository(session, Plan, user.id).get(plan_id)
    out = PlanOut.model_validate(plan.result)
    out.status = plan.status
    out.stale = plan.status is PlanStatus.DRAFT and plan.fingerprint != await fingerprint(
        session, user, today
    )
    return out


async def apply_plan(
    session: AsyncSession, user: User, plan_id: UUID, req: ApplyRequest, today: date
) -> ApplyResponse:
    plan = await OwnedRepository(session, Plan, user.id).get(plan_id)
    if plan.status is not PlanStatus.DRAFT:
        raise ConflictError(f"This plan was already {plan.status.value}.")
    if plan.fingerprint != await fingerprint(session, user, today):
        raise ConflictError(
            "Your money or items changed since this plan was made. Run the planner again.",
            extra={"stale": True},
        )
    out = PlanOut.model_validate(plan.result)
    wanted = set(req.item_ids) if req.item_ids is not None else None
    repo = OwnedRepository(session, PlannedItem, user.id)
    applied: list[UUID] = []
    skipped: list[SkippedOut] = []
    for d in out.decisions:
        if wanted is not None and d.item_id not in wanted:
            continue
        changes = d.changes
        if d.requires_reserve_approval and not req.allow_reserve:
            if d.alternative_changes is None:
                skipped.append(
                    SkippedOut(item_id=d.item_id, reason="Needs approval to use the reserve")
                )
                continue
            changes = d.alternative_changes  # the later, reserve-safe date
        values: dict[str, Any] = {}
        if changes.target_date is not None:
            values["target_date"] = changes.target_date.to
        if changes.status is not None:
            values["status"] = changes.status.to
        if not values:
            continue
        await repo.update(d.item_id, d.item_version, values)
        applied.append(d.item_id)
    if wanted is not None:
        unknown = wanted - {d.item_id for d in out.decisions}
        skipped += [SkippedOut(item_id=i, reason="Not part of this plan") for i in sorted(unknown)]
    plan.status = PlanStatus.APPLIED
    plan.applied_at = utcnow()
    return ApplyResponse(plan_id=plan.id, status=plan.status, applied=applied, skipped=skipped)
