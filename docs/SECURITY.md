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
| Input | Strict Pydantic schemas (`extra="forbid"`), URL scheme validation, LIKE-wildcard escaping, 1 MB proxy body cap, proxy path-traversal rejection |
| AI | Optional and per user; keys encrypted at rest (Fernet) and never returned; assistant and planner rate-limited per user (20 and 30 per minute); model output schema-constrained and re-validated; user text treated as data, not instructions; numbers in summaries must come from the engine; every failure falls back to the offline assistant |
| Privacy | Minimal data collection; full JSON export; permanent account deletion (cascading) |
| Supply chain | Locked runtime Python dependencies + `pip-audit`; `npm audit` on production dependencies in CI |

## Known, accepted advisories

| Advisory | Package path | Why accepted |
|---|---|---|
| [GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) (braces ≤ 3.0.3, ReDoS-style stack exhaustion) | `eslint-config-next → fast-glob → micromatch → braces` (**dev-only**) | No patched release exists yet. It is reachable only through attacker-controlled glob patterns passed to the lint tool on a developer machine, and it is not part of the production bundle or image. CI blocks on any production-dependency advisory. Revisit when a fix ships. |
