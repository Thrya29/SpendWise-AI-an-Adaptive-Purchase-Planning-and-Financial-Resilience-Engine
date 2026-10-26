"""Regression guard: planning must keep beating simple budgeting rules on avoidable overdrafts.

Runs a smaller version of ``research/planner_benchmark.py`` on the report's seed.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.planner_benchmark import report, run  # noqa: E402


def test_planner_prevents_overdrafts_the_rules_cause() -> None:
    result = run(24, seed=2026)
    rows = result["rows"]
    assert isinstance(rows, dict)
    impulse, buffer = rows["impulse"], rows["buffer"]
    for name in ("spendwise-once", "spendwise-reserve", "spendwise", "deadline-first"):
        overdraft = rows[name].avoidable_overdraft
        assert overdraft < buffer.avoidable_overdraft < impulse.avoidable_overdraft, name
    # Replanning with the reserve is at least as good as the careful rule on hard deadlines.
    assert rows["spendwise-reserve"].hard_needs_on_time >= buffer.hard_needs_on_time
    assert "## Findings" in report(result, 24, 2026)
