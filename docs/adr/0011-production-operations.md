# ADR 0011: Production operations on a single Compose host

**Status:** Accepted · 2026-10-26

## Context
SpendWise is ready for real users once it can be deployed, watched, backed up and restored by
one person, and once CI proves that the deployed shape works, not just the code.

## Decision
* **One host, Docker Compose.** PostgreSQL, Redis, API (2 Uvicorn workers), worker and web,
  with Caddy in front for HTTPS (`docker-compose.https.yml`, automatic certificates, HSTS).
  Nothing but Caddy is published. This fits a pilot and small communities. Scaling out
  would mean a managed database and several API replicas, and the app is stateless apart from
  PostgreSQL and Redis, so that path stays open.
* **The CI stack job is the release gate.** Every push builds the images, starts the whole
  stack with health checks, runs a Playwright test on a phone-sized browser (sign up, import a
  statement, run the planner, no console or CSP errors, no 5xx, no horizontal scroll), runs a
  45-second load test that fails on any 5xx, then backs up, restores into a separate database
  and compares rows and the migration version.
* **Logs, not a metrics stack.** The API already writes JSON request logs with duration and
  request ID. Slow requests (over 1 s) are logged as warnings, and `/readyz` checks PostgreSQL and
  Redis. With two Uvicorn processes, in-process metrics would need Prometheus multiprocess
  mode. That moving part isn't worth it at this size, and any log shipper can alert on the
  messages listed in DEPLOYMENT.md.
* **Worker liveness by heartbeat.** The worker touches a file after every cycle, failed or not.
  The container is unhealthy only if the loop stops. Data-source outages are logged and the last
  good data stays visible with its date.
* **Defence in depth on input size.** 1 MB request bodies (3.5 MB for statement uploads only),
  enforced by both the web proxy and the API, including bodies sent without a Content-Length.
* **CSP** with `'self'` sources only, `frame-ancestors 'none'`, `object-src 'none'`.
  `'unsafe-inline'` remains for scripts and styles, which Next.js hydration and the charts need.
  A nonce-based policy is the next step.
* **Plain SQL backups** (`pg_dump` piped to gzip, integrity-checked, 14 kept), a restore script
  that can load into a separate database for drills, and a documented off-server copy.
* **The solver must never fail a request, and must stay fast.** Measuring scaling showed slow
  typical plans, 13 s worst cases and poor time-limited plans. Four changes fix this:
  * one running total of spending per pay day, instead of one constraint per record-low day
    over every purchase option (same optimum on 60 of 60 random instances, a far smaller model);
  * a greedy, always-safe starting plan as the solver hint;
  * cumulative spend cached as prefix sums when explaining decisions;
  * LP linearization (level 2).

  The typical plan (25 items, 6 months) went from about 2 s to about 50 ms, and the slowest
  measured request from 13 s to about 6 s with a sensible plan. If the solver still returns no
  plan, nothing is scheduled and the plan says so (`solver.status = "timeout"`). Results:
  [planner-scaling.md](../results/planner-scaling.md).

## Consequences
* A single host is a single point of failure. Recovery is restoring the latest off-server backup
  on a new host, so RPO is up to a day with daily backups and RTO is about an hour.
* No built-in dashboards; operators rely on logs, `docker compose ps` and an uptime check.
