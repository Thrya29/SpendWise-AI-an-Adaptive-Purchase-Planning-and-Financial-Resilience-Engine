from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import SessionDep, UserDep, user_today
from app.core.errors import DomainValidationError
from app.domain.cashflow import Emergency, IncomeShock, ReservePolicy, Scenario, project
from app.domain.money import Money
from app.domain.recurrence import add_months
from app.schemas.projection import (
    CashEventOut,
    MonthOut,
    PlannedCheckOut,
    ProjectionRequest,
    ProjectionResponse,
)
from app.services.ledger import load_planning_inputs

router = APIRouter(prefix="/projection", tags=["planning"])


@router.post("", response_model=ProjectionResponse)
async def run_projection(
    body: ProjectionRequest, user: UserDep, session: SessionDep
) -> ProjectionResponse:
    """Project cash flow under an optional salary shock and emergencies (what-if analysis)."""
    today = user_today(user)
    start = body.start or today
    end = add_months(start, body.horizon_months)
    inputs = await load_planning_inputs(session, user, today, include_planned=body.include_planned)
    cur = inputs.currency

    emergencies = []
    for em in body.emergencies:
        on = em.on or start
        if not start <= on <= end:
            raise DomainValidationError(
                f"Emergency '{em.name}' falls outside the projection window"
            )
        emergencies.append(Emergency(em.name, Money(em.amount_minor, cur), on))

    shock = None
    if body.shock is not None:
        shock = IncomeShock(body.shock.months, body.shock.starts_on or start, body.shock.mode)

    reserve = ReservePolicy(
        months_of_essentials=body.reserve_months
        if body.reserve_months is not None
        else user.reserve_months,
        min_buffer=user.reserve_buffer_minor,
    )
    p = project(
        opening_balance=inputs.opening_balance,
        start=start,
        end=end,
        incomes=inputs.incomes,
        obligations=inputs.obligations,
        planned=inputs.planned,
        scenario=Scenario(shock=shock, emergencies=tuple(emergencies)),
        reserve=reserve,
    )
    return ProjectionResponse(
        currency=p.currency,
        start=p.start,
        end=p.end,
        opening_balance_minor=p.opening_balance,
        closing_balance_minor=p.closing_balance,
        monthly_essentials_minor=p.monthly_essentials,
        reserve_required_minor=p.reserve_required,
        min_balance_minor=p.min_balance,
        min_balance_on=p.min_balance_on,
        first_reserve_breach_on=p.first_reserve_breach_on,
        first_negative_on=p.first_negative_on,
        runway_months=p.runway_months,
        is_safe=p.is_safe,
        months=[
            MonthOut(
                month=m.month,
                inflow_minor=m.inflow,
                essential_outflow_minor=m.essential_outflow,
                discretionary_outflow_minor=m.discretionary_outflow,
                planned_outflow_minor=m.planned_outflow,
                emergency_outflow_minor=m.emergency_outflow,
                closing_balance_minor=m.closing_balance,
                min_balance_minor=m.min_balance,
            )
            for m in p.months
        ],
        events=[
            CashEventOut(
                on=e.on,
                kind=e.kind,
                label=e.label,
                amount_minor=e.amount,
                balance_after_minor=e.balance_after,
                ref=e.ref,
            )
            for e in p.events
        ],
        planned_checks=[
            PlannedCheckOut(
                item_id=c.ref,
                name=c.name,
                on=c.on,
                amount_minor=c.amount,
                balance_after_minor=c.balance_after,
                keeps_reserve=c.keeps_reserve,
                stays_solvent=c.stays_solvent,
            )
            for c in p.planned_checks
        ],
        warnings=inputs.warnings,
    )
