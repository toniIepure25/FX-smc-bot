"""Tests for data quality diagnostics."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from fx_smc_bot.config import Timeframe, TradingPair
from fx_smc_bot.data.diagnostics import DiagnosticReport, format_diagnostic_report, run_diagnostics
from fx_smc_bot.data.models import BarSeries


def _make_clean_series(n: int = 100) -> BarSeries:
    """Create a clean BarSeries with no issues."""
    start = np.datetime64("2024-01-02T00:00", "ns")
    timestamps = np.array(
        [start + np.timedelta64(i * 15, "m") for i in range(n)],
        dtype="datetime64[ns]",
    )
    rng = np.random.default_rng(42)
    close = 1.1 + np.cumsum(rng.normal(0, 0.0005, n))
    opens = np.roll(close, 1)
    opens[0] = close[0]
    high = np.maximum(opens, close) + rng.uniform(0, 0.001, n)
    low = np.minimum(opens, close) - rng.uniform(0, 0.001, n)

    return BarSeries(
        pair=TradingPair.EURUSD, timeframe=Timeframe.M15,
        timestamps=timestamps, open=opens, high=high, low=low, close=close,
    )


class TestRunDiagnostics:
    def test_clean_data_high_quality(self) -> None:
        series = _make_clean_series()
        report = run_diagnostics(series)
        assert report.quality_score > 0.8
        assert report.total_bars == 100

    def test_empty_data(self) -> None:
        series = BarSeries(
            pair=TradingPair.EURUSD, timeframe=Timeframe.M15,
            timestamps=np.array([], dtype="datetime64[ns]"),
            open=np.array([], dtype=np.float64),
            high=np.array([], dtype=np.float64),
            low=np.array([], dtype=np.float64),
            close=np.array([], dtype=np.float64),
        )
        report = run_diagnostics(series)
        assert report.quality_score == 0.0

    def test_stale_prices_detected(self) -> None:
        series = _make_clean_series(50)
        # Make 10 consecutive bars with same close
        series.close[20:30] = 1.1
        report = run_diagnostics(series, stale_threshold=5)
        assert report.stale_price_sequences > 0

    def test_zero_range_detected(self) -> None:
        series = _make_clean_series(50)
        series.high[10:15] = series.low[10:15]
        report = run_diagnostics(series)
        assert report.zero_range_bars >= 5


class TestFormatReport:
    def test_format_produces_string(self) -> None:
        series = _make_clean_series()
        report = run_diagnostics(series)
        text = format_diagnostic_report(report)
        assert "Data Quality" in text
        assert "EURUSD" in text
