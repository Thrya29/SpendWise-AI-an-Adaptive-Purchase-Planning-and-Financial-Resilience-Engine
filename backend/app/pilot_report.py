"""Print the pilot report (aggregates only).

Usage:  python -m app.pilot_report [--out report.md]
In Docker:  docker compose exec api python -m app.pilot_report
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.core.db import dispose_engine, get_sessionmaker
from app.services.pilot_report import build_report


async def _build() -> str:
    try:
        async with get_sessionmaker()() as session:
            return await build_report(session, datetime.now(UTC).date())
    finally:
        await dispose_engine()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=None)
    out = parser.parse_args().out
    text = asyncio.run(_build())
    if out is None:
        sys.stdout.buffer.write(text.encode())
    else:
        out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
