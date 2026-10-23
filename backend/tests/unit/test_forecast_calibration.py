"""Regression guard: forecasts must stay better than climatology and well calibrated.

Runs a smaller version of ``research/forecast_calibration.py`` on the held-out seed.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.forecast_calibration import run  # noqa: E402


def test_forecasts_beat_climatology_and_are_calibrated() -> None:
    result = run(800, seed=11)
    assert result["skill"] > 0.12, result["skill"]
    assert result["ece"] < 0.07, result["ece"]
