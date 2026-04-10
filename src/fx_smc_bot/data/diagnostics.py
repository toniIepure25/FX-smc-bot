"""Data quality diagnostics: comprehensive per-dataset integrity checks.

Goes beyond basic validation to detect subtle data issues that affect
backtest reliability: missing bars during trading hours, extreme returns,
suspicious spread patterns, and stale-price sequences.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from fx_smc_bot.config import PAIR_PIP_INFO, TIMEFRAME_MINUTES, Timeframe, TradingPair
from fx_smc_bot.data.models import BarSeries


@dataclass(slots=True)
class DiagnosticReport:
    pair: str
    timeframe: str
    total_bars: int
    date_range: str
    missing_bar_count: int
    missing_bar_pct: float
    duplicate_count: int
    zero_range_bars: int
    extreme_return_count: int
    extreme_return_threshold: float
    stale_price_sequences: int
    mean_spread: float | None
    max_spread: float | None
    quality_score: float
    issues: list[str] = field(default_factory=list)


def run_diagnostics(
    series: BarSeries,
    extreme_return_sigmas: float = 5.0,
    stale_threshold: int = 5,
) -> DiagnosticReport:
    """Run comprehensive data quality diagnostics on a BarSeries."""
    n = len(series)
    pair_str = series.pair.value
    tf_str = series.timeframe.value
    issues: list[str] = []

    if n == 0:
        return DiagnosticReport(
            pair=pair_str, timeframe=tf_str, total_bars=0,
            date_range="N/A", missing_bar_count=0, missing_bar_pct=0.0,
            duplicate_count=0, zero_range_bars=0, extreme_return_count=0,
            extreme_return_threshold=extreme_return_sigmas,
            stale_price_sequences=0, mean_spread=None, max_spread=None,
            quality_score=0.0, issues=["Empty dataset"],
        )

    ts = series.timestamps
    start_str = str(ts[0])[:19]
    end_str = str(ts[-1])[:19]

    # Duplicates
    unique_count = len(np.unique(ts))
    dup_count = n - unique_count
    if dup_count > 0:
        issues.append(f"{dup_count} duplicate timestamps")

    # Missing bars (during weekdays only)
    expected_minutes = TIMEFRAME_MINUTES.get(series.timeframe, 15)
    diffs_min = np.diff(ts).astype("timedelta64[m]").astype(np.int64)
    # Count gaps > 2x expected that fall on weekdays
    gap_threshold = expected_minutes * 2
    missing_count = 0
    for i, diff in enumerate(diffs_min):
        if diff > gap_threshold:
            ts_dt = ts[i].astype("datetime64[us]").astype(datetime)
            if ts_dt.weekday() < 5:  # not weekend
                missing_count += int(diff / expected_minutes) - 1

    total_expected = n + missing_count
    missing_pct = missing_count / total_expected if total_expected > 0 else 0.0
    if missing_pct > 0.05:
        issues.append(f"High missing bar rate: {missing_pct:.1%}")

    # Zero-range bars
    ranges = series.high - series.low
    zero_range = int(np.sum(ranges == 0))
    if zero_range > n * 0.01:
        issues.append(f"{zero_range} zero-range bars ({zero_range / n:.1%})")

    # Extreme returns
    returns = np.diff(series.close) / series.close[:-1]
    returns = returns[np.isfinite(returns)]
    ret_std = float(np.std(returns)) if len(returns) > 1 else 1.0
    threshold = extreme_return_sigmas * ret_std
    extreme_count = int(np.sum(np.abs(returns) > threshold)) if ret_std > 0 else 0
    if extreme_count > 0:
        issues.append(f"{extreme_count} extreme returns (>{extreme_return_sigmas}σ)")

    # Stale price detection (same close for N+ consecutive bars)
    stale_seqs = 0
    run_length = 1
    for i in range(1, n):
        if series.close[i] == series.close[i - 1]:
            run_length += 1
            if run_length == stale_threshold:
                stale_seqs += 1
        else:
            run_length = 1
    if stale_seqs > 0:
        issues.append(f"{stale_seqs} stale-price sequences (>={stale_threshold} bars)")

    # Spread analysis
    mean_spread = None
    max_spread = None
    if series.spread is not None:
        valid_spreads = series.spread[~np.isnan(series.spread)]
        if len(valid_spreads) > 0:
            mean_spread = float(np.mean(valid_spreads))
            max_spread = float(np.max(valid_spreads))

    # Quality score: 1.0 = perfect, degrades with issues
    score = 1.0
    score -= min(missing_pct * 5, 0.3)
    score -= min(dup_count / max(n, 1) * 10, 0.2)
    score -= min(extreme_count / max(n, 1) * 5, 0.2)
    score -= min(stale_seqs / max(n, 1) * 50, 0.15)
    score -= min(zero_range / max(n, 1) * 2, 0.15)
    score = max(score, 0.0)

    return DiagnosticReport(
        pair=pair_str, timeframe=tf_str, total_bars=n,
        date_range=f"{start_str} -> {end_str}",
        missing_bar_count=missing_count, missing_bar_pct=missing_pct,
        duplicate_count=dup_count, zero_range_bars=zero_range,
        extreme_return_count=extreme_count,
        extreme_return_threshold=extreme_return_sigmas,
        stale_price_sequences=stale_seqs,
        mean_spread=mean_spread, max_spread=max_spread,
        quality_score=round(score, 3), issues=issues,
    )


def format_diagnostic_report(report: DiagnosticReport) -> str:
    lines = [
        f"=== Data Quality: {report.pair} / {report.timeframe} ===",
        f"  Bars:           {report.total_bars:,d}",
        f"  Date range:     {report.date_range}",
        f"  Missing bars:   {report.missing_bar_count:,d} ({report.missing_bar_pct:.1%})",
        f"  Duplicates:     {report.duplicate_count}",
        f"  Zero-range:     {report.zero_range_bars}",
        f"  Extreme returns: {report.extreme_return_count} (>{report.extreme_return_threshold}σ)",
        f"  Stale prices:   {report.stale_price_sequences}",
    ]
    if report.mean_spread is not None:
        lines.append(f"  Mean spread:    {report.mean_spread:.6f}")
        lines.append(f"  Max spread:     {report.max_spread:.6f}")
    lines.append(f"  Quality score:  {report.quality_score:.3f}")
    if report.issues:
        lines.append("  Issues:")
        for issue in report.issues:
            lines.append(f"    - {issue}")
    return "\n".join(lines)
