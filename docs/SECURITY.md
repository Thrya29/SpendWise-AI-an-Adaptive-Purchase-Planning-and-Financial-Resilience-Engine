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
| Transport & headers | `nosniff`, `X-Frame-Options: DENY`, strict referrer policy, restrictive permissions policy, `no-store` on API responses, no `X-Powered-By` |
| Network | Only the web container is published, on 127.0.0.1; API, DB and Redis are on private networks |
| Containers | Non-root users, read-only root filesystems, `no-new-privileges`, health checks |
| Input | Strict Pydantic schemas (`extra="forbid"`), URL scheme validation, LIKE-wildcard escaping, 1 MB proxy body cap (3.5 MB for statement uploads only), proxy path-traversal rejection |
| AI | Optional and per user; keys encrypted at rest (Fernet) and never returned; assistant and planner rate-limited per user (20 and 30 per minute); model output schema-constrained and re-validated; user text treated as data, not instructions; numbers in summaries must come from the engine; every failure falls back to the offline assistant |
| Outbound fetching (SSRF) | http/https on default ports only; every resolved address must be public (loopback, private, link-local incl. 169.254.169.254, multicast and reserved refused, also as IPv4-mapped IPv6); redirects re-validated per hop (max 3); 2 MB / 15 s caps; HTML only; robots.txt honoured; per-user rate limits. Residual DNS-rebinding risk documented in ADR 0006 |
| Privacy | Minimal data collection; full JSON export; permanent account deletion (cascading); uploaded bank statements are parsed in memory and never stored or logged, only the confirmed income and bills are saved |
| Email | Optional SMTP, opt-in per user, at most one digest a day; STARTTLS or implicit TLS with certificate verification; CR/LF stripped from headers so item names cannot inject headers; failures retried after an hour, not in a loop |
| Supply chain | Locked runtime Python dependencies + `pip-audit`; `npm audit` on production dependencies in CI |

## Known, accepted advisories

| Advisory | Package path | Why accepted |
|---|---|---|
| [GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) (braces ≤ 3.0.3, ReDoS-style stack exhaustion) | `eslint-config-next → fast-glob → micromatch → braces` (**dev-only**) | No patched release exists yet. It is reachable only through attacker-controlled glob patterns passed to the lint tool on a developer machine, and it is not part of the production bundle or image. CI blocks on any production-dependency advisory. Revisit when a fix ships. |
