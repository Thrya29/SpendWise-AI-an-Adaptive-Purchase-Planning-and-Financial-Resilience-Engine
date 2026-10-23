"""Create a .env file with freshly generated secrets for Docker Compose.

Usage:  python scripts/generate_env.py [--force]
Uses only the standard library so it runs before any dependency is installed.
"""

from __future__ import annotations

import base64
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / ".env"


def main() -> int:
    if TARGET.exists() and "--force" not in sys.argv:
        print(f"{TARGET} already exists. Re-run with --force to overwrite.")
        return 1
    values = {
        "POSTGRES_USER": "spendwise",
        "POSTGRES_PASSWORD": secrets.token_urlsafe(32),
        "POSTGRES_DB": "spendwise",
        "SPENDWISE_JWT_SECRET": secrets.token_urlsafe(48),
        "SPENDWISE_ENCRYPTION_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "SPENDWISE_COOKIE_SECURE": "true",
        "WEB_PORT": "3000",
    }
    TARGET.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    print(f"Wrote {TARGET} with new random secrets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
