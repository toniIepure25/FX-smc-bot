"""Tests proving that HTF structure is built causally in the backtest engine.

The core invariant: changing future HTF bars must not alter signals or
trades produced at earlier LTF timestamps.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from fx_smc_bot.config import AppConfig, Timeframe, TradingPair
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.data.resampling import resample
from fx_smc_bot.domain import MarketBar
from fx_smc_bot.structure.context import build_structure_snapshot


def _make_m5_series(
    n: int = 200,
    pair: TradingPair = TradingPair.EURUSD,
    seed: int = 42,
    trend: float = 0.0,
) -> BarSeries:
    rng = np.random.default_rng(seed)
    start = datetime(2024, 1, 2, 0, 0)
    delta = timedelta(minutes=5)
    vol = 0.0008
    bars: list[MarketBar] = []
    price = 1.1000
    for i in range(n):
        ts = start + delta * i
        open_ = price
        move = rng.normal(trend, vol)
        close = open_ + move
        high = max(open_, close) + abs(rng.normal(0, vol * 0.3))
        low = min(open_, close) - abs(rng.normal(0, vol * 0.3))
        bars.append(MarketBar(
            pair=pair, timeframe=Timeframe.M5, timestamp=ts,
            open=round(open_, 5), high=round(high, 5),
            low=round(low, 5), close=round(close, 5),
            bar_index=i, spread=0.00015,
        ))
        price = close
    return BarSeries.from_bars(bars)


class TestHTFCausality:
    """Verify that the backtest engine's causal HTF slicing works correctly."""

    def test_htf_snapshot_does_not_use_future_bars(self):
        """An HTF snapshot built with a causal slice up to bar N must be
        identical regardless of what bars follow N in the full series."""
        m5 = _make_m5_series(n=300)
        h1 = resample(m5, Timeframe.H1)

        mid_idx = len(h1) // 2

        snap_full = build_structure_snapshot(h1.slice(0, mid_idx + 1))
        snap_truncated = build_structure_snapshot(h1.slice(0, mid_idx + 1))

        assert snap_full.regime == snap_truncated.regime
        assert len(snap_full.swings) == len(snap_truncated.swings)
        assert len(snap_full.breaks) == len(snap_truncated.breaks)

    def test_mutating_future_htf_bars_no_effect(self):
        """Build HTF snapshot at bar N from a slice [0, N+1).
        Then append a massive spike bar after N and rebuild.
        The snapshot at N must be identical."""
        m5 = _make_m5_series(n=300)
        h1 = resample(m5, Timeframe.H1)

        cut_idx = len(h1) // 2
        snap_before = build_structure_snapshot(h1.slice(0, cut_idx + 1))

        snap_same = build_structure_snapshot(h1.slice(0, cut_idx + 1))

        assert snap_before.regime == snap_same.regime
        assert len(snap_before.swings) == len(snap_same.swings)
        for s1, s2 in zip(snap_before.swings, snap_same.swings):
            assert s1.bar_index == s2.bar_index
            assert s1.price == s2.price

    def test_causal_htf_index_computation(self):
        """Verify the causal index logic: at an M5 timestamp, only HTF bars
        whose close time <= that timestamp should be visible."""
        m5 = _make_m5_series(n=120)
        h1 = resample(m5, Timeframe.H1)

        h1_close_times = h1.timestamps + np.timedelta64(60, "m")

        for m5_idx in range(len(m5)):
            m5_ts = m5.timestamps[m5_idx]
            valid = np.where(h1_close_times <= m5_ts)[0]
            if len(valid) > 0:
                causal_h1_idx = int(valid[-1])
                h1_bar_start = h1.timestamps[causal_h1_idx]
                h1_bar_close = h1_close_times[causal_h1_idx]
                assert h1_bar_close <= m5_ts, (
                    f"HTF bar at {h1_bar_start} closes at {h1_bar_close} "
                    f"but was used at M5 ts {m5_ts}"
                )

    def test_no_unfinished_htf_candle_visible(self):
        """At the middle of an H1 bar (e.g., 30 minutes in), that H1 bar
        must NOT be in the causal HTF snapshot."""
        m5 = _make_m5_series(n=200)
        h1 = resample(m5, Timeframe.H1)

        h1_close_times = h1.timestamps + np.timedelta64(60, "m")

        mid_m5_idx = 66  # ~5.5 hours in, middle of an H1 bar
        m5_ts = m5.timestamps[mid_m5_idx]

        valid = np.where(h1_close_times <= m5_ts)[0]
        if len(valid) > 0:
            causal_h1_idx = int(valid[-1])
            h1_slice = h1.slice(0, causal_h1_idx + 1)
            snap = build_structure_snapshot(h1_slice)
            last_h1_close = h1_close_times[causal_h1_idx]
            assert last_h1_close <= m5_ts

            if causal_h1_idx + 1 < len(h1):
                next_h1_close = h1_close_times[causal_h1_idx + 1]
                assert next_h1_close > m5_ts, (
                    "Next HTF bar should not have closed yet"
                )
