# ADR 0004: Authentication and session model

**Status:** Accepted · 2026-10-23

## Decision
* Passwords hashed with **Argon2id** (argon2-cffi defaults). Login runs in roughly constant time
  for unknown emails, via a dummy hash.
* **Access token:** a 15-minute HS256 JWT (`typ=access`), kept **in browser memory only**.
* **Refresh token:** 48 random bytes in an `httpOnly; Secure; SameSite=Strict` cookie scoped to
  `/api/v1/auth`. Only its SHA-256 is stored.
* **Rotation with reuse detection:** each refresh revokes the presented token and issues a new one
  in the same *family*. Presenting a revoked token revokes the whole family, which signs out a
  thief and the victim alike. The revocation is committed before the 401 is returned.
* Password change revokes all of the user's sessions.
* Login and registration are rate-limited per IP and per email (Redis fixed window, with an
  in-process fallback for development).
* The browser talks only to its own origin. Next.js proxies `/api/v1/*` to the private API, so no
  CORS exposure is needed in the default deployment.

## Consequences
* XSS cannot read a persisted token. A page reload restores the session from the refresh cookie.
* `Secure` cookies work on `http://localhost` in Chromium and Firefox. Other hostnames need HTTPS,
  which is the expected production setup.
