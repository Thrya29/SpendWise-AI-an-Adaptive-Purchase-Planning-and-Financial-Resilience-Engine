"""Savings and investment *education*: calculators, simulations and reference data.

Nothing here recommends buying or selling a security (SEBI investment-adviser rules).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date, timedelta
from decimal import Decimal
from itertools import pairwise
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import delete, select

from app.ai.formatting import format_amount
from app.api.deps import SessionDep, UserDep, user_today
from app.core.db import utcnow
from app.core.errors import DomainValidationError, NotFoundError
from app.core.ratelimit import enforce
from app.domain.investing import FundStats, NavPoint, deterministic_value, fund_stats, simulate
from app.domain.money import Money
from app.domain.savings import (
    PURITY,
    fd_maturity,
    jewellery_bill,
    per_gram_from_ounce,
    premature_payout,
    savings_balance,
)
from app.models.entities import FundScheme, WatchedFund
from app.schemas.insights import (
    DepositIn,
    DepositOut,
    FundDetailOut,
    FundOut,
    GoldOut,
    JewelleryIn,
    JewelleryOut,
    SafeToLockOut,
    SimulateIn,
    SimulateOut,
    WatchIn,
)
from app.services import fx_service, insights_data, insights_service

router = APIRouter(tags=["insights"])
ACTIVE_DAYS = 30
DEFAULT_RETURN, DEFAULT_VOLATILITY = Decimal(10), Decimal(15)


async def get_data_client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(headers={"User-Agent": "SpendWise/1.0"}) as client:
        yield client


DataClientDep = Annotated[httpx.AsyncClient, Depends(get_data_client)]


def _pct(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(round(value * 100, 2)))


@router.get("/insights/safe-to-lock", response_model=SafeToLockOut)
async def safe_to_lock(
    user: UserDep,
    session: SessionDep,
    months: Annotated[int, Query(ge=1, le=60)] = 12,
    protect_delay_months: Annotated[int, Query(ge=0, le=6)] = 1,
) -> SafeToLockOut:
    r = await insights_service.safe_to_lock(
        session, user, user_today(user), months=months, protect_delay_months=protect_delay_months
    )
    amount = format_amount(r.amount, r.currency)
    explanation = (
        f"You could keep about {amount} in a deposit for {months} months and still cover every "
        f"planned purchase and your reserve, even in '{r.binding_scenario}'. Your tightest day "
        f"would be {r.lowest_point_on.isoformat()}."
        if r.amount > 0
        else f"Nothing can be locked away for {months} months without putting a plan or your "
        f"reserve at risk in '{r.binding_scenario}'."
    )
    return SafeToLockOut(
        currency=r.currency, amount_minor=r.amount, months=r.months,
        available_now_minor=r.available_now, reserve_minor=r.reserve,
        monthly_essentials_minor=r.monthly_essentials, runway_months=r.runway_months,
        binding_scenario=r.binding_scenario, lowest_point_on=r.lowest_point_on,
        explanation=explanation, warnings=r.warnings,
    )  # fmt: skip


@router.post("/insights/deposit", response_model=DepositOut)
async def compare_deposit(body: DepositIn, user: UserDep) -> DepositOut:
    """FD versus savings account, plus what breaking the FD early would pay."""
    p = body.principal_minor
    fd = fd_maturity(p, body.fd_rate_percent, body.months)
    savings = savings_balance(p, body.savings_rate_percent, body.months)
    out = DepositOut(
        currency=user.base_currency, fd_maturity_minor=fd, fd_interest_minor=fd - p,
        savings_balance_minor=savings, savings_interest_minor=savings - p,
        fd_advantage_minor=fd - savings,
        notes=[
            "FDs of 6 months or more are compounded quarterly; shorter ones pay simple interest.",
            "Interest is taxable at your slab rate; banks may deduct TDS. Tax is not shown here.",
        ],
    )  # fmt: skip
    if body.premature:
        pm = premature_payout(
            p, body.fd_rate_percent, body.months, body.premature.held_months,
            rate_for_held_period_percent=body.premature.rate_for_held_period_percent,
            penalty_percent=body.premature.penalty_percent,
        )  # fmt: skip
        out.premature_payout_minor = pm.payout
        out.premature_effective_rate_percent = pm.effective_rate_percent
        out.premature_interest_lost_minor = pm.interest_lost
    return out


async def _scheme(session: SessionDep, code: int) -> FundScheme:
    scheme = await session.get(FundScheme, code)
    if scheme is None:
        raise NotFoundError("fund not found")
    return scheme


def _active(s: FundScheme, cutoff: date) -> bool:
    """Has a valid NAV published recently (segregated portfolios can show 0.0000)."""
    return s.nav is not None and s.nav_date is not None and s.nav_date >= cutoff


def _fund_out(s: FundScheme, today_active: bool) -> FundOut:
    return FundOut(
        scheme_code=s.scheme_code, name=s.name, fund_house=s.fund_house, category=s.category,
        isin=s.isin, nav=s.nav, nav_date=s.nav_date, active=today_active,
    )  # fmt: skip


@router.post("/insights/simulate", response_model=SimulateOut)
async def simulate_investment(
    body: SimulateIn, user: UserDep, session: SessionDep, client: DataClientDep
) -> SimulateOut:
    """A range of possible outcomes for a lump sum and/or monthly SIP, never a single promise."""
    if body.initial_minor + body.monthly_minor == 0:
        raise DomainValidationError("Enter a lump sum, a monthly amount, or both")
    ret, vol = body.annual_return_percent, body.annual_volatility_percent
    source = "Your assumptions"
    if body.scheme_code is not None:
        stats = await _fund_statistics(session, client, body.scheme_code)
        if stats is None or stats.volatility is None or not stats.cagr:
            raise DomainValidationError("Not enough history for this fund to use as assumptions")
        window = max(stats.cagr)
        ret = ret if ret is not None else Decimal(str(round(stats.cagr[window] * 100, 2)))
        vol = vol if vol is not None else Decimal(str(round(stats.volatility * 100, 2)))
        source = f"This fund's last {window} year(s) of history ({insights_data.HISTORY_SOURCE})"
    elif ret is None or vol is None:
        ret, vol = ret or DEFAULT_RETURN, vol or DEFAULT_VOLATILITY
        source = "Illustrative defaults (10% return, 15% volatility); change them to your own"
    sim = simulate(
        initial=body.initial_minor, monthly=body.monthly_minor, months=body.months,
        annual_return=float(ret) / 100, annual_volatility=float(vol) / 100,
    )  # fmt: skip
    fd = (
        deterministic_value(
            initial=body.initial_minor, monthly=body.monthly_minor, months=body.months,
            annual_rate=float(body.compare_fd_rate_percent) / 100,
        )
        if body.compare_fd_rate_percent is not None
        else None
    )  # fmt: skip
    return SimulateOut(
        currency=user.base_currency, months=sim.months, invested_minor=sim.invested,
        p10_minor=sim.p10, p50_minor=sim.p50, p90_minor=sim.p90,
        probability_of_loss=round(sim.probability_of_loss, 4),
        median_max_drawdown=round(sim.median_max_drawdown, 4), annual_return_percent=ret,
        annual_volatility_percent=vol, assumptions_source=source, fd_value_minor=fd,
        paths=sim.paths, seed=sim.seed,
    )  # fmt: skip


def _words(text: str) -> list[str]:
    return "".join(c.lower() if c.isalnum() else " " for c in text).split()


def _relevance(name: str, query: str) -> tuple[int, int, int, str]:
    """Sort key: exact phrase first, then words in the query's order, then shorter names.

    Plain alphabetical order put "Nifty Next 50" above "Nifty 50" for "nifty 50".
    """
    words, q = _words(name), _words(query)
    text, phrase = " ".join(words), " ".join(q)
    adjacent = sum(1 for a, b in pairwise(q) if f"{a} {b}" in text)
    return (0 if phrase in text else 1, -adjacent, len(words), name)


@router.get("/funds/search", response_model=list[FundOut])
async def search_funds(
    user: UserDep,
    session: SessionDep,
    q: Annotated[str, Query(min_length=3, max_length=100)],
    include_inactive: bool = False,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[FundOut]:
    cutoff = user_today(user) - timedelta(days=ACTIVE_DAYS)
    query = select(FundScheme)
    for word in q.split()[:6]:
        escaped = word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(FundScheme.name.ilike(f"%{escaped}%", escape="\\"))
    if not include_inactive:
        query = query.where(FundScheme.nav.is_not(None), FundScheme.nav_date >= cutoff)
    candidates = list(await session.scalars(query.limit(500)))
    ranked = sorted(candidates, key=lambda s: _relevance(s.name, q))
    return [_fund_out(s, _active(s, cutoff)) for s in ranked[:limit]]


@router.get("/funds/watchlist", response_model=list[FundOut])
async def watchlist(user: UserDep, session: SessionDep) -> list[FundOut]:
    cutoff = user_today(user) - timedelta(days=ACTIVE_DAYS)
    rows = await session.scalars(
        select(FundScheme)
        .join(WatchedFund, WatchedFund.scheme_code == FundScheme.scheme_code)
        .where(WatchedFund.user_id == user.id)
        .order_by(FundScheme.name)
    )
    return [_fund_out(s, _active(s, cutoff)) for s in rows]


@router.post("/funds/watchlist", status_code=status.HTTP_201_CREATED, response_model=FundOut)
async def watch(body: WatchIn, user: UserDep, session: SessionDep) -> FundOut:
    scheme = await _scheme(session, body.scheme_code)
    exists = await session.scalar(
        select(WatchedFund.id).where(
            WatchedFund.user_id == user.id, WatchedFund.scheme_code == body.scheme_code
        )
    )
    if exists is None:
        session.add(WatchedFund(user_id=user.id, scheme_code=body.scheme_code))
    cutoff = user_today(user) - timedelta(days=ACTIVE_DAYS)
    return _fund_out(scheme, _active(scheme, cutoff))


@router.delete("/funds/watchlist/{scheme_code}", status_code=status.HTTP_204_NO_CONTENT)
async def unwatch(scheme_code: int, user: UserDep, session: SessionDep) -> None:
    await session.execute(
        delete(WatchedFund).where(
            WatchedFund.user_id == user.id, WatchedFund.scheme_code == scheme_code
        )
    )


async def _fund_statistics(
    session: SessionDep, client: httpx.AsyncClient, code: int
) -> FundStats | None:
    await _scheme(session, code)
    points = await insights_data.history(session, code)
    if not points or points[-1][0] < utcnow().date() - timedelta(days=4):
        try:
            await insights_data.refresh_history(session, client, code)
            points = await insights_data.history(session, code)
        except insights_data.SourceUnavailableError:
            pass  # fall back to whatever history is stored
    return fund_stats([NavPoint(d, float(n)) for d, n in points]) if points else None


@router.get("/funds/{scheme_code}", response_model=FundDetailOut)
async def fund_detail(
    scheme_code: int, user: UserDep, session: SessionDep, client: DataClientDep
) -> FundDetailOut:
    """Facts about one fund you chose: latest NAV and how it behaved historically."""
    await enforce(f"funds:{user.id}", limit=30)
    scheme = await _scheme(session, scheme_code)
    stats = await _fund_statistics(session, client, scheme_code)
    watched = await session.scalar(
        select(WatchedFund.id).where(
            WatchedFund.user_id == user.id, WatchedFund.scheme_code == scheme_code
        )
    )
    cutoff = user_today(user) - timedelta(days=ACTIVE_DAYS)
    base = _fund_out(scheme, _active(scheme, cutoff))
    cagr = stats.cagr if stats else {}
    return FundDetailOut(
        **base.model_dump(),
        source=insights_data.AMFI_SOURCE,
        history_source=insights_data.HISTORY_SOURCE if stats else None,
        history_points=stats.points if stats else 0,
        history_from=stats.first_day if stats else None,
        cagr_percent={f"{y}y": Decimal(str(round(v * 100, 2))) for y, v in cagr.items()},
        volatility_percent=_pct(stats.volatility) if stats else None,
        max_drawdown_percent=_pct(stats.max_drawdown) if stats else None,
        watched=watched is not None,
    )


@router.get("/gold", response_model=GoldOut)
async def gold_reference(user: UserDep, session: SessionDep) -> GoldOut:
    latest = await insights_data.latest_gold(session)
    cur = user.base_currency
    if latest is None:
        return GoldOut(available=False, currency=cur)
    per_gram_usd = per_gram_from_ounce(latest.price_per_ounce_minor)
    fx = fx_service.Converter(cur, await fx_service.latest_table(session, user_today(user)))
    converted, note = fx.convert(Money(per_gram_usd, "USD"), "Gold reference")
    if converted is None:
        return GoldOut(available=False, currency=cur, fx_note=note)
    k22 = round(Decimal(converted.amount_minor) * PURITY["22K"] / PURITY["24K"])
    return GoldOut(
        available=True, currency=cur, per_gram_24k_minor=converted.amount_minor,
        per_gram_22k_minor=k22, usd_per_ounce=format_amount(latest.price_per_ounce_minor, "USD"),
        observed_at=latest.observed_at, source=latest.source, fx_note=note,
    )  # fmt: skip


@router.post("/gold/refresh", response_model=GoldOut)
async def refresh_gold(user: UserDep, session: SessionDep, client: DataClientDep) -> GoldOut:
    await enforce(f"gold:{user.id}", limit=10, window_seconds=3600)
    try:
        await insights_data.refresh_gold(session, client)
    except insights_data.SourceUnavailableError as exc:
        raise DomainValidationError("The gold price source is unavailable right now.") from exc
    return await gold_reference(user, session)


@router.post("/gold/jewellery", response_model=JewelleryOut)
async def jewellery_estimate(body: JewelleryIn, user: UserDep) -> JewelleryOut:
    bill = jewellery_bill(
        rate_24k_per_gram=body.rate_24k_per_gram_minor, weight_grams=body.weight_grams,
        purity=body.purity, making_percent=body.making_percent,
        making_per_gram=body.making_per_gram_minor, gst_percent=body.gst_percent,
        hallmark_fee=body.hallmark_fee_minor,
    )  # fmt: skip
    return JewelleryOut(
        currency=user.base_currency, gold_value_minor=bill.gold_value,
        making_charges_minor=bill.making_charges, hallmark_fee_minor=bill.hallmark_fee,
        gst_minor=bill.gst, total_minor=bill.total,
        effective_per_gram_minor=bill.effective_per_gram,
    )  # fmt: skip
