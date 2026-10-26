# SpendWise AI

**An adaptive purchase-planning and financial-resilience engine.**

Most expense trackers tell you what you already spent. SpendWise plans what you *will* spend. You
list your **needs, wants and desires** (a work laptop, a salon visit, a trip) and SpendWise checks
each one against your real cash flow. It tells you whether you can buy it without breaking your
emergency reserve, and what happens if your **salary is delayed** or an **emergency** hits.

> SpendWise provides planning tools and educational information, not regulated financial advice.

---

## What works today

| Area | Capability |
|---|---|
| **Needs, wants & desires** | Add, edit, delete and filter planned spending: products, services, travel, experiences, subscriptions. Each item has a priority (1–5), target date, hard/soft/flexible deadline, lead time, price ceiling, link and location. Items can be marked purchased, postponed, or moved back to planned. |
| **Money** | Accounts with live balances, recurring income (weekly/monthly/quarterly/yearly/one-off), recurring expenses flagged as essential or discretionary, and one-off transactions. |
| **Emergency reserve** | A configurable reserve (N months of essentials + a buffer) that plans must never spend. |
| **What-if simulator** | Projects the balance day by day for 3–24 months. You can apply a **salary delay** (paid late as arrears) or **salary loss** for N months, plus an **unexpected expense**. You see when you'd dip into the reserve or run out, and which planned purchases stay safe. |
| **Purchase planner** | Chooses the best month and day to buy each item, or postpones it, so your balance never drops below your reserve, **even if salary is late or lost** (you choose which shocks to guard against). It is an exact constraint solver (OR-Tools CP-SAT), not a heuristic. Every decision has a reason: postponed items show the exact extra money needed and by when. Nothing changes until you approve, and using the reserve always needs explicit consent. |
| **Prices from links** | Paste a product link and SpendWise reads the price the page publishes for search engines (schema.org data), along with its source, time and stock status. Every check is kept as price history, and you can also record quotes from local shops. Your planning price changes only when you click *Use this price* or turn on *Track this price*. Every price shows where it came from and how old it is. |
| **Price alerts** | For tracked items: a price at or below your maximum, a drop of 5% or more, back in stock, or checks that keep failing. A background worker re-checks twice a day, politely spacing out visits to each site. |
| **Price outlook** | *"64% chance of ₹53,000 or less by 22 Nov (medium confidence)"*, based only on the item's own price history. It counts past sales and drops, and shows no forecast at all with less than 5 checks over 14 days. On held-out simulated data it is well calibrated: **+0.227 Brier skill, 3% calibration error** ([results](docs/results/forecast-calibration.md)). The planner uses it when you're waiting for a better price. |
| **Alternatives** | Mark items as alternatives (laptop A *or* B) and the planner buys at most one, the best fit. If buying a fallback now would rule out a preferred item that's waiting for a sale, the plan says so. With your Claude key, **Find current alternatives** runs a live web search and keeps only products found on the cited pages. |
| **Savings & investing (education)** | **Money you could set aside**: the most you could lock in a fixed deposit while every plan and your reserve stay safe, even if salary is late. Also: **FD vs. savings account** (including the cost of breaking an FD early), a **SIP/lump-sum simulator** that shows a range of outcomes and the chance of loss rather than one promised return, **mutual-fund NAVs** from AMFI (official) with each fund's real historical returns, volatility and worst fall, and **gold** with every jewellery charge shown separately. Education, not advice: it never tells you what to buy. |
| **Multi-currency** | Daily European Central Bank reference rates. Accounts, income and items in other currencies are **converted exactly, with the rate and date shown**. Currencies without a reference rate are left out with a warning, never guessed. |
| **"Describe it" entry** | Type *"work laptop for 75k by 15 Dec, must have"* and the assistant fills in the form for you to review. |
| **AI assistant mode** | Each user chooses the built-in assistant (offline, no API key) or **their own Claude API key**, which is stored encrypted and never shown again. AI only reads text and writes summaries. It never does the math: a summary containing any number the engine didn't produce is rejected. Any AI failure falls back to the built-in assistant. |
| **Account & privacy** | Sign-up with country, city, address and timezone; password change; full JSON data export; permanent account deletion. |

### Worked example (it's a regression test)

Savings ₹60,000 · essentials ₹20,000/month · salary ₹45,000 delayed two months · ₹10,000 emergency ·
2-month reserve (₹40,000). SpendWise reports that the reserve is breached on the first rent day, the
low point is ₹10,000, and both delayed salaries arrive together later. See
[`test_reference_scenario_salary_delayed_two_months_with_emergency`](backend/tests/unit/test_cashflow.py).

## Architecture at a glance

```
Browser ──► Next.js (UI + same-origin /api proxy) ──► FastAPI ──► PostgreSQL
                                                         ├──────► Redis (rate limits)
             Worker (same image): FX + price checks ─────┘   ──► public web (SSRF-guarded)
```

* **Deterministic core.** Balances, projections and reserve checks are pure Python with integer
  minor-unit money. The LLM never does arithmetic.
* **Modular monolith.** Clean module boundaries (ledger, planning, auth) without the operational
  cost of microservices at this scale.
* **Typed contract.** The frontend's TypeScript types are generated from the API's OpenAPI schema,
  and CI fails if they drift.

Full design: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · Planner: [ADR 0005](docs/adr/0005-robust-purchase-scheduling.md) · Market data: [ADR 0006](docs/adr/0006-market-data-provenance.md) · Forecasting: [ADR 0007](docs/adr/0007-price-drop-forecasting.md) · Savings & investing: [ADR 0008](docs/adr/0008-savings-and-investment-education.md) · Decisions: [docs/adr/](docs/adr/) ·
Security: [docs/SECURITY.md](docs/SECURITY.md)

## Run it

Requires Docker with Compose v2.

```bash
python scripts/generate_env.py      # creates .env with fresh random secrets (never committed)
docker compose up --build -d
# open http://localhost:3000
```

Only the web app is published, and only on `127.0.0.1`. The API, database and Redis stay on
private Docker networks. Migrations run automatically when the API starts.

Local development without Docker: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Quality gates

Every push runs in CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)):

| Backend | Frontend |
|---|---|
| ruff lint + format · mypy `--strict` | ESLint (0 warnings) · Prettier · `tsc` |
| pytest on **SQLite and PostgreSQL 16** | Vitest unit tests |
| Property-based tests (Hypothesis): money invariants, and *no plan ever breaks the reserve* | Production `next build` |
| Coverage gate ≥ 85% (currently ~96%) · forecast calibration regression test | Generated API types must match the schema |
| Migration ↔ model drift check + up/down round-trip | `npm audit` on production deps |
| `pip-audit` on the locked runtime deps | Docker images must build |

Warnings are treated as errors in the backend test suite.

## Tech stack

**Backend:** Python 3.12 · FastAPI · SQLAlchemy 2 (async) · Alembic · Pydantic v2 · OR-Tools CP-SAT ·
Anthropic SDK (optional, user's own key) · Argon2 · PyJWT ·
PostgreSQL 16 · Redis 7  
**Frontend:** Next.js 16 (App Router, standalone output) · React 19 · TypeScript (strict) ·
Tailwind CSS 4 · Recharts  
**Ops:** Docker Compose · GitHub Actions

## Roadmap

Built in phases. Each phase ships tested and documented before the next begins.

| Phase | Scope | Status |
|---|---|---|
| 0 | Foundation: repo, CI, Docker, auth, security baseline | ✅ Done |
| 1 | Ledger, needs/wants/desires CRUD, cash-flow projection, salary-delay & emergency scenarios | ✅ Done |
| 2 | Purchase **scheduling optimizer** (CP-SAT): buy now / schedule / postpone / wait for price / use reserve with consent; replanning; AI item entry and summaries (built-in or Claude) | ✅ Done |
| 3 | Market data: link prices with provenance, price history and quotes, multi-currency (ECB), alerts, background worker; SSRF-hardened fetching | ✅ Done |
| 4 | Calibrated price-drop forecasting (measured on held-out data), alternatives groups in the planner, verified web search for current alternatives | ✅ Done |
| 5 | Savings & investment education: safe-to-lock amount, FD vs. savings, Monte Carlo SIP simulator, AMFI NAVs with fund history, gold reference and jewellery bill (sourced and timestamped; no advice) | ✅ Done |
| 6 | Research benchmark: planner vs. baseline budgeting rules under simulated shocks | ⏳ Next |
| 7 | Production hardening: observability, load tests, deployment guide | Planned |

## Honest limits

* **Not every shop can be read.** Big marketplaces often block automated checks or build the price
  with JavaScript. SpendWise then says it found no price, and you enter one yourself or record a
  quote. It never scrapes visible text or guesses.
* The gold price is an international reference and reads lower than Indian retail rates, which add
  import duty and GST. The app says so, and the jewellery estimate uses your jeweller's quote.
* Exchange rates are daily ECB reference rates, so they're not live market quotes. About 30
  currencies are covered; others (e.g. AED, SAR) are left out of planning with a warning.

## License

Copyright © 2026 Thrya29. All rights reserved.
