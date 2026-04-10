"""Data validation: gap detection, price sanity, deduplication.

All functions operate on BarSeries and return diagnostic information
or a cleaned BarSeries.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fx_smc_bot.config import TIMEFRAME_MINUTES
from fx_smc_bot.data.models import BarSeries


@dataclass(frozen=True, slots=True)
class ValidationReport:
    total_bars: int
    duplicate_timestamps: int
    zero_range_bars: int
    negative_range_bars: int
    timestamp_gaps: int
    high_low_violations: int
    is_clean: bool


def validate(series: BarSeries, max_gap_multiple: int = 3) -> ValidationReport:
    """Run all quality checks on a BarSeries."""
    n = len(series)
    if n == 0:
        return ValidationReport(0, 0, 0, 0, 0, 0, True)

    # Duplicate timestamps
    ts = series.timestamps
    unique_count = len(np.unique(ts))
    dup_count = n - unique_count

    # Zero-range and negative-range bars
    ranges = series.high - series.low
    zero_range = int(np.sum(ranges == 0))
    neg_range = int(np.sum(ranges < 0))

    # High-low violations (open or close outside high-low)
    hl_violations = int(np.sum(
        (series.open > series.high) | (series.open < series.low) |
        (series.close > series.high) | (series.close < series.low)
    ))

    # Timestamp gaps
    gap_count = 0
    if n > 1:
        diffs = np.diff(ts).astype("timedelta64[m]").astype(np.int64)
        expected_minutes = TIMEFRAME_MINUTES.get(series.timeframe, 15)
        threshold = expected_minutes * max_gap_multiple
        gap_count = int(np.sum(diffs > threshold))

    is_clean = (dup_count == 0 and neg_range == 0 and hl_violations == 0)
    return ValidationReport(
        total_bars=n,
        duplicate_timestamps=dup_count,
        zero_range_bars=zero_range,
        negative_range_bars=neg_range,
        timestamp_gaps=gap_count,
        high_low_violations=hl_violations,
        is_clean=is_clean,
    )


def deduplicate(series: BarSeries) -> BarSeries:
    """Remove duplicate timestamps, keeping the last occurrence."""
    ts = series.timestamps
    _, idx = np.unique(ts, return_index=True)
    idx = np.sort(idx)
    return BarSeries(
        pair=series.pair, timeframe=series.timeframe,
        timestamps=ts[idx],
        open=series.open[idx], high=series.high[idx],
        low=series.low[idx], close=series.close[idx],
        volume=series.volume[idx] if series.volume is not None else None,
        spread=series.spread[idx] if series.spread is not None else None,
    )


def fix_high_low(series: BarSeries) -> BarSeries:
    """Ensure high >= max(open, close) and low <= min(open, close)."""
    h = np.maximum(series.high, np.maximum(series.open, series.close))
    lo = np.minimum(series.low, np.minimum(series.open, series.close))
    return BarSeries(
        pair=series.pair, timeframe=series.timeframe,
        timestamps=series.timestamps.copy(),
        open=series.open.copy(), high=h, low=lo, close=series.close.copy(),
        volume=series.volume.copy() if series.volume is not None else None,
        spread=series.spread.copy() if series.spread is not None else None,
    )
