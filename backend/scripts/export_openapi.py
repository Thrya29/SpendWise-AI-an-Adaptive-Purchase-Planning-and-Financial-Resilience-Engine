"""Write the API's OpenAPI document to stdout or a file (used to generate frontend types).

Usage: python scripts/export_openapi.py [output.json]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    from app.main import create_app  # noqa: PLC0415 - keep import cost out of module load

    document = json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(document, encoding="utf-8")
    else:
        sys.stdout.write(document)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
