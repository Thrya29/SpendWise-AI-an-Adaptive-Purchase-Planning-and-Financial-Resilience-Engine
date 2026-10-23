# Architecture

## 1. Goals and non-goals

**Goals**

1. Tell a user, for any planned purchase, whether it is affordable **without breaching a protected
   emergency reserve**, both now and under adverse scenarios (salary delay or loss, emergencies).
2. Keep every money figure **exact and reproducible**: the same inputs always give the same answer.
3. Work fully **without any LLM**. AI is an optional layer for language, never for arithmetic.
4. Be operable by one engineer: one `docker compose up`, automatic migrations, health checks.

**Non-goals (for now)**

* Bank-account aggregation (requires regulated data-access agreements).
* Personalised securities recommendations (regulated investment advice).
* Guaranteed coverage of every retailer's live prices.

## 2. System context

```
                 ┌───────────────────────── private network: frontend ─────────────────────┐
 Browser ──HTTPS─► web (Next.js standalone)                                                │
   │             │  • static UI shells                                                     │
   │             │  • /api/v1/* route handler = same-origin proxy (header allowlist)       │
   │             └──────────────┬───────────────────────────────────────────────────────────┘
   │                            │ HTTP (internal)
   │             ┌──────────────▼──────────── private network: backend ───────────────────┐
   │             │ api (FastAPI, uvicorn)                                                  │
   │             │  api/      routers, dependencies, problem+json errors                   │
   │             │  services/ auth, owner-scoped repository, ledger assembly               │
   │             │  domain/   money, recurrence, cash-flow projection  (pure, no I/O)      │
   │             │  models/   SQLAlchemy entities          core/  config, db, security     │
   │             └──────┬───────────────────────────┬──────────────────────────────────────┘
   │                    │                           │
   │              PostgreSQL 16                 Redis 7 (rate-limit counters)
```

Only `web` is published to the host, on `127.0.0.1`. `api`, `db` and `redis` are reachable solely
on internal Docker networks. Containers run as non-root with read-only root filesystems and
`no-new-privileges`.

## 3. Key design decisions

| Decision | Why | ADR |
|---|---|---|
| Modular monolith, not microservices | One team, one deployable; module boundaries keep a later split cheap | [0001](adr/0001-modular-monolith.md) |
| Integer minor-unit money | Floats cannot represent 0.1; financial results must be exact | [0002](adr/0002-integer-money.md) |
| Deterministic engine, optional LLM | Users must trust the numbers; the app must work offline | [0003](adr/0003-deterministic-core-optional-llm.md) |
| Same-origin proxy + in-memory access token | Strict cookies and no token in localStorage | [0004](adr/0004-auth-and-session-model.md) |

## 4. Domain model

```
User 1─* Account 1─* Transaction
  │1─* IncomeStream        (amount, frequency, anchor, end, subject_to_shocks)
  │1─* Obligation          (amount, frequency, anchor, end, essential)
  │1─* PlannedItem         (tier: need|want|desire, kind, priority 1-5, price, qty,
  │                         target_date, deadline: hard|soft|none, lead_time, status)
  │1─* RefreshToken        (sha256 hash, family_id for reuse detection)
  └1─* AuditEvent          (entity, action, field-level diff)
```

* Every user-owned table carries `user_id` with `ON DELETE CASCADE`. Every query goes through
  `OwnedRepository`, which always filters by owner, so another user's row returns **404, not 403**
  and IDs cannot be probed.
* Mutable rows carry a `version` column (SQLAlchemy `version_id_col`). Updates must send the
  version they read, and stale writes return **409** with the current version.
* Every create, update and delete writes an `AuditEvent` with a field-level diff.

## 5. The cash-flow engine (`backend/app/domain/cashflow.py`)

Pure function: `project(opening_balance, start, end, incomes, obligations, planned, scenario,
reserve) -> Projection`.

1. **Expand recurrences** (`recurrence.py`). Monthly schedules clamp to month end (31 Jan →
   28/29 Feb) while keeping the anchor day for later months.
2. **Apply shocks** to income streams marked `subject_to_shocks`:
   * *Delayed N months*: payments due in `[shock_start, shock_start + N months)` arrive N months
     later. The engine looks back 24 months so arrears from before the horizon are included.
   * *Lost*: those payments never arrive.
3. **Order events** by date, applying **outflows before inflows on the same day** (conservative).
4. **Walk the ledger**, recording each balance, the low point, the first reserve breach and the
   first negative day, plus a check for every planned purchase (keeps reserve? stays solvent?).
5. **Reserve** = monthly-equivalent essentials × reserve months + buffer. The weekly → monthly
   conversion is ×52/12 with banker's rounding.

Planned items are paid on `max(today, target_date − lead_time_days)`, the latest date that still
gets the item there in time.

**Invariants verified by property-based tests** (`tests/property/`):

* Conservation: closing = opening + Σ events, and each event's running balance is exact.
* A salary shock never raises the balance at any month end, the low point or the closing balance.
* Adding spending never improves the low point and never delays the first reserve breach.

## 6. API conventions

* Base path `/api/v1`, OpenAPI at `/api/v1/openapi.json`.
* Money is always `*_minor: int` plus an ISO 4217 `currency` (the Stripe convention).
* Errors use RFC 9457 `application/problem+json` with a `request_id` for support. Validation
  errors include per-field `errors[]`.
* Lists are paginated (`limit` ≤ 200, `offset`) and return `{items, total, limit, offset}`.
* `PATCH` is partial, but `version` is required. Fields that cannot be null are rejected explicitly
  instead of being written as null.

## 7. Frontend

* **Next.js 16** with `cacheComponents`. Pages are prerendered static shells, and data loads on the
  client with the user's access token. The only dynamic route is the `/api/v1/[...path]` proxy.
* The proxy reads `API_INTERNAL_URL` at request time, so one image serves every environment. It
  forwards an allowlist of headers in each direction, rejects path traversal, caps bodies at 1 MB,
  times out after 30 s, and turns upstream failures into a problem+json 502.
* `src/lib/api/schema.d.ts` is generated from the backend's OpenAPI. CI regenerates it and fails
  on any diff.
* User-entered amounts are parsed as **strings into BigInt minor units**, so `0.29` is exactly
  29 cents.

## 8. Operations

* `/healthz` (liveness) and `/readyz` (checks the database) power the Docker health checks.
  Compose starts `api` only after `db` and `redis` are healthy, and `web` only after `api`.
* Structured JSON logs carry a `request_id` that is propagated end to end (`X-Request-ID`).
* The API refuses to start in production with default secrets, short JWT secrets or insecure
  cookies.

## 9. Purchase planner (`backend/app/domain/planner.py`)

A robust scheduling problem solved with OR-Tools CP-SAT. The full formulation, alternatives and
consequences are in [ADR 0005](adr/0005-robust-purchase-scheduling.md). In short:

* **Decision:** `x[i,t]`, buy item *i* in period *t* (the rest of this month, then calendar months
  up to today + horizon), or postpone.
* **Safety:** in every protected scenario (as expected, plus chosen shocks such as "salary 2 months
  late") and on every record-low day, cumulative spending ≤ the day's low balance − the reserve.
* **Objective:** priority-weighted value. Needs count for more than wants, and wants more than
  desires; value decays when an item is late or bought needlessly early.
* **Consent:** a hard-deadline need that only fits on time by using the reserve is proposed as
  `use_reserve` with its reserve-safe alternative date. Applying without approval uses the safe
  date.
* **Output:** one decision per item (`buy_now`, `schedule`, `postpone`, `wait_price`,
  `use_reserve`) with a reason, the exact shortfall for postponed items, and a preview of the item
  changes that applying would make.

```
POST /planner/plans          solve and save a draft (nothing changes yet)
GET  /planner/plans/{id}     re-read it; "stale": true once any underlying data changes
POST /planner/plans/{id}/apply   {item_ids?, allow_reserve}; 409 if stale or already applied
POST /assistant/parse-item   free text -> draft item for the user to review
```

## 10. Assistant layer (`backend/app/ai/`)

```
service.py ── picks the user's provider ──► anthropic_provider.py (user's key, Claude)
     │                                   └► mock.py (rules + templates, offline)
     └── any provider failure → mock, with a notice shown to the user
```

* **Item intake:** a JSON schema constrains Claude's output, which is then re-validated. Prices
  come back as decimal strings and our code converts them. The mock parses "75k", "1.2 lakh",
  "₹1,500", "next month", "15 Dec", "this weekend", tiers, types, priority and quantity.
* **Plan summaries:** written from engine-computed facts only. A Claude summary containing any
  number not present in those facts is rejected. If a protected scenario breaks the reserve even
  with no purchases, the summary says so, and it never claims safety for that scenario.

## 11. Market data (`backend/app/market/`, `services/market_service.py`, `services/fx_service.py`)

Policy and alternatives: [ADR 0006](adr/0006-market-data-provenance.md).

```
link ─► fetcher.py (SSRF guard, robots.txt, caps) ─► extract.py (JSON-LD / microdata / OpenGraph)
                                                        │
              PriceObservation (append-only, full provenance) ◄─┘
                │ track_price on, or "Use this price" ─► PlannedItem.estimated_price_minor
                └ alert rules ─► Alert (price target, ≥5% drop, back in stock, failing checks)

ECB reference rates (daily) ─► FxRate rows ─► RateTable ─► Converter used by projection & planner
```

* **Worker** (`python -m app.worker`, same image, `worker` service in Compose): every minute it
  refreshes FX if the last fetch is over 6 hours old, then checks up to 20 tracked items due for a
  check (12-hour cadence), at least 10 s apart per site. Each check is its own transaction.
* **Conversion** happens once, in `load_planning_inputs`. Projections and plans receive base-currency
  amounts plus a note for every conversion. Plan decisions also keep the item's original price and
  currency for display.

## 12. What comes next

Phase 4 turns the price history into **forecasts**: the probability of reaching a target price
within N days, with calibrated uncertainty. It also adds discovery of alternative products, so
the planner's cost can become a distribution `p_i(t)` instead of a single number.
