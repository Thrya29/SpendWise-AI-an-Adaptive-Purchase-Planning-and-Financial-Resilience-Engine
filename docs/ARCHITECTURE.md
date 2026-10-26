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
  date. If on time is solvent only in the expected scenario, the safe decision stands and the
  decision carries an `on_time_*` option (date, scenarios at risk, deepest shortfall). It is
  applied only for items listed in `on_time_item_ids`.
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

## 12. Forecasting and alternatives

* **Forecasts** (`domain/forecast.py`, [ADR 0007](adr/0007-price-drop-forecasting.md)): the chance
  of the price reaching a target within H days, from Poisson-modelled drop episodes in the item's
  own history. `GET /items/{id}/forecast` defaults to the item's maximum price (or 10% off) and
  the time until it must be paid for.
* **Calibration** (`research/forecast_calibration.py`): a reproducible synthetic backtest. A
  smaller version runs in CI as a regression guard.
* **Alternatives groups** (`planned_items.alternative_group`): the CP-SAT model adds one
  at-most-one constraint across every period variable of a group's members. Members not chosen
  get the decision `alternative` with the chosen item's ID. A fallback bought while a
  higher-ranked member waits for a price gets a `group_note` stating the trade-off.
* **Finding alternatives**: Claude with the `web_search_20260209` server tool (`pause_turn` is
  resumed up to 3 times). A suggestion is kept only if its page appears among that request's
  search results. Suggested products open the item form **without a price**.

## 13. Savings and investment education

[ADR 0008](adr/0008-savings-and-investment-education.md) sets the boundary: explain and simulate,
never recommend a security.

* `domain/savings.py`: FD maturity (quarterly compounding from 6 months), early withdrawal, savings
  account interest, and gold purity and jewellery bills. All in exact Decimal on minor units.
* `domain/investing.py`: fund statistics from NAV history (1/3/5-year annualised returns, volatility,
  maximum drawdown) and a seeded Monte Carlo of SIP or lump-sum outcomes.
* `services/insights_service.py`: the safe-to-lock amount uses the same cash-flow engine and
  planning inputs as the planner.
* `services/insights_data.py`: the AMFI file parser and batched upsert (PostgreSQL and SQLite
  dialects), the mfapi.in history loader, and the gold spot price. All come from fixed URLs with
  size and time caps. The worker refreshes them (AMFI and fund history daily, gold every 6 hours).

## 14. Planner benchmark

`research/planner_benchmark.py` ([results](results/planner-benchmark.md),
[ADR 0009](adr/0009-planner-benchmark.md)) lives 500 synthetic households through six months of
one realised world each (calm, salary delayed 1–3 months, salary lost 2–4 months, an emergency,
or both). Every policy sees only the past and obeys the same purchase guard (never pay with money
not held that day):

* Rules: `impulse` (buy when wanted or affordable), `50/30/20` (wants from 30% of income received),
  `buffer` (keep two months of essentials, except hard deadlines).
* Planner: once on day 0, or replanned monthly and after a missed salary or emergency, with the
  reserve alone or with delay protection; plus a `deadline-first` ablation that patches stage 2
  only inside the benchmark.
* Metrics: avoidable overdraft (negative balance where buying nothing stays positive, with
  Wilson intervals), depth, extra days below reserve, needs on time, and share of the wish list
  bought, overall and per world.

A 24-household version runs in CI and asserts that every planner variant has fewer avoidable
overdrafts than `buffer`, which has fewer than `impulse`.

## 15. Statement import (`domain/statement.py`, `services/import_service.py`)

[ADR 0010](adr/0010-statement-import.md). `POST /imports/statement/preview` takes the file's text
and returns what was read; nothing is stored. The parser:

* finds the header row by its contents (banks put a preamble above the table), tries the sniffed
  delimiter and then `,` tab `;` `|`, and maps columns by name patterns (Narration / Particulars /
  Transaction Remarks; Withdrawal / Debit / DR; Deposit / Credit / CR; a signed Amount with an
  optional Dr/Cr column);
* picks the date format that parses at least 80% of rows (day first unless told otherwise), skips
  footer and summary lines, and sorts rows oldest first;
* checks every row against the running balance, if there is one, and warns about mismatches.

Recurring detection normalises each description into a payee key (UPI/NEFT fields, handles,
references, month names and transfer jargon removed), groups by direction and key, and keeps
groups whose gaps are regular (75% within the band): weekly (5–9 days, at least 3 times),
monthly (25–36) or quarterly (80–100). Keyword hints name common bills and mark them essential.
`POST /imports/statement/apply` creates only what the user confirmed, skips exact duplicates,
and can set an account so that today's balance equals the statement's closing balance.

## 16. Reminders (`services/notification_service.py`, `core/mailer.py`)

The worker calls `notify_users` every tick. For each user, once per local day after
`SPENDWISE_MORNING_HOUR` (7 by default), it creates:

* `bill_shortfall`: the expected-scenario projection for the next 3 days (planned purchases
  included) takes the balance below zero on an essential bill's due date;
* `buy_day`: a planned item's pay date (target date minus lead time) is today;
* `salary_check`: an income subject to shocks was due yesterday.

Each alert has a dedupe key (`uq_alert_dedupe` on user and key), so reruns and restarts never
repeat a reminder; `users.money_checked_on` skips the work for the rest of the day. If the user
opted in and SMTP is configured, unread alerts not yet emailed (from the last 3 days, up to 20)
go out as one digest, at most once per `SPENDWISE_DIGEST_HOURS`. A failed send is retried
after an hour.

## 17. Feedback and pilot measurement

* `POST /feedback` stores a comment with an optional 1–5 rating and the page it came from.
* `GET /feedback/checkin` is due once per month, for the previous month, if the account existed
  for at least two weeks of it; `POST /feedback/checkin` stores three answers (ran short for a
  bill, missed a need's deadline, followed the plan) and is unique per user and month.
* `services/usage.py` records `active` (once per local day, from the auth dependency),
  `statement_imported`, `plan_created`, `plan_applied`, `on_time_chosen`, `checkin` and
  `feedback`, only for users with `share_usage`. The subject is an HMAC of the user id keyed with
  the server's encryption key.
* `python -m app.pilot_report` prints setup progress, weekly active users, 4th-or-5th-week
  retention, check-in outcomes per month and the latest comments. See [PILOT.md](PILOT.md).

## 18. Operations

[ADR 0011](adr/0011-production-operations.md) and the [deployment guide](DEPLOYMENT.md).

* `BodySizeLimitMiddleware` (pure ASGI) returns 413 above 1 MB, or 3.5 MB for
  `/imports/statement/preview`. Declared lengths are checked up front; undeclared bodies are
  buffered up to the limit first.
* `/readyz` checks PostgreSQL and, when configured, Redis. Requests over 1 s log `slow_request`.
* The worker writes a heartbeat after every cycle (the Compose health check reads its age),
  paces reminders to every 5 minutes, and only opens a session for users with something due.
* The planner models one running total of spending per pay day (exactly equivalent to the
  per-record-day constraints and linear in items x periods), starts CP-SAT from a greedy safe
  plan, and turns a time-out without a solution into an empty, explained plan (`timeout`).
  See [planner scaling](results/planner-scaling.md).
* CI's `stack` job runs Compose, the Playwright phone test (`e2e/`), `backend/scripts/loadtest.py`,
  and `scripts/backup.sh` / `scripts/restore.sh --into`.

## 19. Browser extension (`extension/`, `routes/extension.py`)

Manifest V3, no build step. `extract.js` is injected into the active tab only when the user
clicks (`activeTab` + `scripting`) and reads, most reliable first: JSON-LD `Product` offers,
product meta tags and microdata, known Amazon and Flipkart price elements, and finally the
largest-font currency amount near the top of the page (not struck out), marked "please check".
The popup shows the result for confirmation and posts it with an extension key:

```
POST /me/extension-keys          create (shown once)    GET, DELETE /me/extension-keys/{id}
GET  /extension/items            items to attach a price to
POST /extension/capture          {url, price_minor, currency, item_id | new_item, use_price}
```

A capture appends a `PriceObservation` with method `browser`, runs the usual price-drop and
within-limit alerts, and (by default) makes it the planning price. The extractor is tested in a
real browser against sample pages (`e2e/tests/extension-extract.spec.ts`).

## 20. What comes next

All seven phases are complete. Candidates for the next round, best decided with
pilot results ([PILOT.md](PILOT.md)):

* Hindi and other Indian languages. This needs translations of all UI text, reviewed by
  native speakers for financial terms.
* A nonce-based Content-Security-Policy, so inline scripts no longer need `'unsafe-inline'`.
* Live bank data through the RBI Account Aggregator framework, which requires a licensed partner.
* PDF statement import for banks that don't offer CSV.
* Publishing the extension in the Chrome Web Store and Edge Add-ons, so it installs in one click.
* Automatic price tracking on large marketplaces through official affiliate APIs (Amazon
  Product Advertising API) or licensed price data, if the project qualifies.
* Repeating the planner benchmark on real (consented, pseudonymous) cash flows.
