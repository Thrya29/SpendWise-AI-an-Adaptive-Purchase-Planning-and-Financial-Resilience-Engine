# Security

## Reporting a vulnerability

Please report suspected vulnerabilities privately through GitHub's **Security → Report a
vulnerability** on this repository. Do not open a public issue.

## Controls in place

| Area | Control |
|---|---|
| Authentication | Argon2id hashes; 15-min in-memory access JWT; rotating refresh cookie (`httpOnly`, `Secure`, `SameSite=Strict`, path-scoped) with family-wide reuse revocation |
| Authorization | Every query is owner-scoped; other users' rows return 404; cross-entity references (account, item) are ownership-checked |
| Abuse | Per-IP and per-email rate limits on login and registration |
| Data integrity | Integer money; DB check constraints; optimistic concurrency (409 on stale writes); audit trail |
| Secrets | `.env` is git-ignored and generated locally; production refuses default or short secrets; user LLM keys encrypted with Fernet and never returned |
| Transport & headers | HTTPS with automatic certificates and HSTS via Caddy (`docker-compose.https.yml`); Content-Security-Policy restricted to `'self'` with `frame-ancestors 'none'`, `object-src 'none'`, `base-uri 'self'` and `form-action 'self'` (`'unsafe-inline'` remains for Next.js hydration; nonces are future work); `nosniff`, `X-Frame-Options: DENY`, strict referrer policy, restrictive permissions policy, `no-store` on API responses, no `X-Powered-By` |
| Network | Only the web container is published, on 127.0.0.1; API, DB and Redis are on private networks |
| Containers | Non-root users, read-only root filesystems, `no-new-privileges`, health checks |
| Input | Strict Pydantic schemas (`extra="forbid"`), URL scheme validation, LIKE-wildcard escaping, 1 MB body cap (3.5 MB for statement uploads only) enforced by both the web proxy and the API, including bodies without Content-Length, proxy path-traversal rejection |
| Browser extension | Keys are scoped to two endpoints (list items, save a confirmed price) by a separate auth dependency; normal session tokens are refused there and extension keys are refused everywhere else. Stored as SHA-256 digests, shown once, at most 5 per user, revocable, rate-limited. The extension uses `activeTab` (reads only the tab the user clicks on) and asks for host permission for the user's SpendWise address only |
| AI | Optional and per user; keys encrypted at rest (Fernet) and never returned; assistant and planner rate-limited per user (20 and 30 per minute); model output schema-constrained and re-validated; user text treated as data, not instructions; numbers in summaries must come from the engine; every failure falls back to the offline assistant |
| Outbound fetching (SSRF) | http/https on default ports only; every resolved address must be public (loopback, private, link-local incl. 169.254.169.254, multicast and reserved refused, also as IPv4-mapped IPv6); redirects re-validated per hop (max 3); 2 MB / 15 s caps; HTML only; robots.txt honoured; per-user rate limits. Residual DNS-rebinding risk documented in ADR 0006 |
| Privacy | Minimal data collection; full JSON export; permanent account deletion (cascading); uploaded bank statements are parsed in memory and never stored or logged, only the confirmed income and bills are saved |
| Research data | Usage statistics are opt-in, keyed-hash pseudonyms (HMAC of the user id), day-level dates and small counts only; erased when the user opts out or deletes the account. Feedback is included in the data export and deleted with the account. The pilot report shows aggregates and comment text, never emails or names |
| Email | Optional SMTP, opt-in per user, at most one digest a day; STARTTLS or implicit TLS with certificate verification; CR/LF stripped from headers so item names cannot inject headers; failures retried after an hour, not in a loop |
| Operations | Daily compressed `pg_dump` backups with integrity check and retention; restore drills into a separate database; `backups/` git-ignored; CI restores a backup on every push |
| Supply chain | Locked runtime Python dependencies + `pip-audit`; `npm audit` on production dependencies in CI |

## Known, accepted advisories

| Advisory | Package path | Why accepted |
|---|---|---|
| [GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) (braces ≤ 3.0.3, ReDoS-style stack exhaustion) | `eslint-config-next → fast-glob → micromatch → braces` (**dev-only**) | No patched release exists yet. It is reachable only through attacker-controlled glob patterns passed to the lint tool on a developer machine, and it is not part of the production bundle or image. CI blocks on any production-dependency advisory. Revisit when a fix ships. |
