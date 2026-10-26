"""Reference data for insights: AMFI NAVs, fund NAV history, and the gold spot price.

Sources (fixed, trusted URLs; responses are size-capped and validated):
* AMFI daily NAV file: official, all schemes, previous business day.
* mfapi.in: free community mirror of AMFI NAV history (labelled as such).
* gold-api.com: international spot price in USD per troy ounce.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import httpx
from sqlalchemy import delete, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import utcnow
from app.domain.money import Money
from app.models.entities import FundNav, FundScheme, GoldPrice

logger = logging.getLogger("spendwise.insights")

AMFI_SOURCE = "AMFI daily NAV file (official)"
HISTORY_SOURCE = "mfapi.in (community mirror of AMFI data)"
GOLD_SOURCE = "gold-api.com international spot price"
MAX_AMFI_BYTES = 20_000_000
MAX_JSON_BYTES = 5_000_000
MIN_SCHEMES = 100  # a shorter AMFI file is treated as a truncated download


class SourceUnavailableError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class SchemeRow:
    scheme_code: int
    name: str
    fund_house: str | None
    category: str | None
    isin: str | None
    nav: str | None
    nav_date: date | None


def _decimal(text: str) -> str | None:
    try:
        value = Decimal(text.strip())
    except (InvalidOperation, ValueError):
        return None
    return str(value) if value.is_finite() and value > 0 else None


def parse_amfi(text: str) -> list[SchemeRow]:
    """Parse AMFI's NAVAll.txt: section headers give the category, plain lines the fund house."""
    rows: list[SchemeRow] = []
    category: str | None = None
    house: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("Scheme Code"):
            continue
        parts = line.split(";")
        if len(parts) < 6:
            if "(" in line and line.endswith(")") and "Schemes" in line:
                category = line[line.index("(") + 1 : -1].strip() or None
            else:
                house = line[:150]
            continue
        code_text, nav_text, date_text = parts[0], parts[-2], parts[-1]
        # Newer files split "Plan" and "Option" into columns; keep them so variants are distinct.
        extra = parts[4:6] if len(parts) >= 8 else []
        name = " - ".join(x.strip() for x in [parts[3], *extra] if x.strip() and x.strip() != "-")
        if not code_text.strip().isdigit():
            continue
        isin = parts[1].strip() if len(parts) > 1 and len(parts[1].strip()) == 12 else None
        try:
            nav_date = datetime.strptime(date_text.strip(), "%d-%b-%Y").date()
        except ValueError:
            nav_date = None
        rows.append(
            SchemeRow(
                int(code_text), name[:300], house, (category or "")[:200] or None,
                isin, _decimal(nav_text), nav_date,
            )
        )  # fmt: skip
    return rows


async def _get(client: httpx.AsyncClient, url: str, max_bytes: int, limit_s: float) -> bytes:
    try:
        async with client.stream("GET", url, timeout=limit_s, follow_redirects=True) as response:
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise SourceUnavailableError("Response too large")
            return bytes(body)
    except httpx.HTTPError as exc:
        raise SourceUnavailableError(str(exc)) from exc


async def upsert_schemes(session: AsyncSession, rows: Iterable[SchemeRow]) -> int:
    dialect = session.bind.dialect.name if session.bind else "sqlite"
    insert = postgresql.insert if dialect == "postgresql" else sqlite.insert
    batch: list[dict[str, object]] = []
    total = 0
    now = utcnow()

    async def flush() -> None:
        if not batch:
            return
        stmt = insert(FundScheme).values(batch)
        stmt = stmt.on_conflict_do_update(
            index_elements=[FundScheme.scheme_code],
            set_={c: getattr(stmt.excluded, c) for c in
                  ("name", "fund_house", "category", "isin", "nav", "nav_date", "updated_at")},
        )  # fmt: skip
        await session.execute(stmt)
        batch.clear()

    for r in rows:
        batch.append({
            "scheme_code": r.scheme_code, "name": r.name, "fund_house": r.fund_house,
            "category": r.category, "isin": r.isin, "nav": r.nav, "nav_date": r.nav_date,
            "updated_at": now,
        })  # fmt: skip
        total += 1
        if len(batch) >= 500:
            await flush()
    await flush()
    return total


async def refresh_schemes(session: AsyncSession, client: httpx.AsyncClient) -> int:
    body = await _get(client, get_settings().amfi_url, MAX_AMFI_BYTES, 60.0)
    rows = parse_amfi(body.decode("utf-8", errors="replace"))
    if len(rows) < MIN_SCHEMES:
        raise SourceUnavailableError("AMFI file looked incomplete")
    count = await upsert_schemes(session, rows)
    logger.info("amfi_refreshed", extra={"schemes": count})
    return count


def parse_history(data: object) -> list[tuple[date, str]]:
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise SourceUnavailableError("Unexpected history format")
    out: dict[date, str] = {}
    for entry in data["data"]:
        try:
            day = datetime.strptime(str(entry["date"]), "%d-%m-%Y").date()
        except (KeyError, TypeError, ValueError):
            continue
        nav = _decimal(str(entry.get("nav", "")))
        if nav is not None:
            out[day] = nav
    return sorted(out.items())


async def refresh_history(session: AsyncSession, client: httpx.AsyncClient, code: int) -> int:
    body = await _get(client, f"{get_settings().mfapi_url}/{code}", MAX_JSON_BYTES, 30.0)
    try:
        points = parse_history(json.loads(body))
    except json.JSONDecodeError as exc:
        raise SourceUnavailableError("History was not valid JSON") from exc
    await session.execute(delete(FundNav).where(FundNav.scheme_code == code))
    session.add_all(FundNav(scheme_code=code, nav_date=d, nav=n) for d, n in points)
    await session.flush()
    return len(points)


async def history(session: AsyncSession, code: int) -> list[tuple[date, str]]:
    rows = await session.execute(
        select(FundNav.nav_date, FundNav.nav)
        .where(FundNav.scheme_code == code)
        .order_by(FundNav.nav_date)
    )
    return [(d, n) for d, n in rows.all()]


async def refresh_gold(session: AsyncSession, client: httpx.AsyncClient) -> GoldPrice:
    body = await _get(client, get_settings().gold_url, 100_000, 20.0)
    try:
        data = json.loads(body)
        price = Decimal(str(data["price"]))
        observed = datetime.fromisoformat(str(data["updatedAt"]).replace("Z", "+00:00"))
        currency = str(data.get("currency", "USD")).upper()
    except (json.JSONDecodeError, KeyError, InvalidOperation, ValueError, TypeError) as exc:
        raise SourceUnavailableError("Unexpected gold price format") from exc
    if not price.is_finite() or not Decimal(100) < price < Decimal(100_000) or currency != "USD":
        raise SourceUnavailableError("Implausible gold price")
    row = GoldPrice(
        source=GOLD_SOURCE, currency="USD",
        price_per_ounce_minor=Money.from_decimal(price, "USD").amount_minor, observed_at=observed,
    )  # fmt: skip
    session.add(row)
    await session.flush()
    return row


async def latest_gold(session: AsyncSession) -> GoldPrice | None:
    return await session.scalar(select(GoldPrice).order_by(GoldPrice.observed_at.desc()).limit(1))
