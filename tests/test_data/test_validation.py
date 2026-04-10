"""Tests for data validation."""

from __future__ import annotations

import numpy as np
import pytest

from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.data.validation import ValidationReport, deduplicate, fix_high_low, validate

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from conftest import make_bars


class TestValidation:
    def test_clean_data(self) -> None:
        series = BarSeries.from_bars(make_bars(n=50))
        report = validate(series)
        assert report.total_bars == 50
        assert report.duplicate_timestamps == 0
        assert report.negative_range_bars == 0
        assert report.is_clean

    def test_detects_hl_violations(self) -> None:
        series = BarSeries.from_bars(make_bars(n=10))
        series.high[3] = series.low[3] - 0.001  # intentional violation
        report = validate(series)
        assert report.negative_range_bars >= 1
        assert not report.is_clean

    def test_deduplicate(self) -> None:
        series = BarSeries.from_bars(make_bars(n=10))
        series.timestamps[5] = series.timestamps[4]  # duplicate
        deduped = deduplicate(series)
        assert len(deduped) == 9

    def test_fix_high_low(self) -> None:
        series = BarSeries.from_bars(make_bars(n=10))
        series.high[2] = series.low[2]  # zero range but valid
        fixed = fix_high_low(series)
        assert np.all(fixed.high >= np.maximum(fixed.open, fixed.close))
        assert np.all(fixed.low <= np.minimum(fixed.open, fixed.close))
