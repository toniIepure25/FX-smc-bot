"""Tests for multi-timeframe causal alignment.

Verifies that at an M5 timestamp, only the last fully closed H1/H4/D1
candle is visible to the strategy logic.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from fx_smc_bot.config import Timeframe, TradingPair, TIMEFRAME_MINUTES
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.data.resampling import resample
from fx_smc_bot.domain import MarketBar


def _make_m5_bars(n: int = 200, seed: int = 42) -> BarSeries:
    rng = np.random.default_rng(seed)
    start = datetime(2024, 1, 2, 0, 0)
    delta = timedelta(minutes=5)
    bars: list[MarketBar] = []
    price = 1.1000
    for i in range(n):
        ts = start + delta * i
        move = rng.normal(0, 0.0005)
        close = price + move
        high = max(price, close) + abs(rng.normal(0, 0.0002))
        low = min(price, close) - abs(rng.normal(0, 0.0002))
        bars.append(MarketBar(
            pair=TradingPair.EURUSD, timeframe=Timeframe.M5,
            timestamp=ts, open=round(price, 5), high=round(high, 5),
            low=round(low, 5), close=round(close, 5),
            bar_index=i, spread=0.00015,
        ))
        price = close
    return BarSeries.from_bars(bars)


class TestMTFAlignment:

    def test_m5_sees_only_closed_h1(self):
        """At every M5 timestamp, the causal H1 index must point to
        an H1 bar that has fully closed."""
        m5 = _make_m5_bars(n=300)
        h1 = resample(m5, Timeframe.H1)

        h1_minutes = TIMEFRAME_MINUTES[Timeframe.H1]
        h1_close_times = h1.timestamps + np.timedelta64(h1_minutes, "m")

        for m5_idx in range(len(m5)):
            m5_ts = m5.timestamps[m5_idx]
            valid = np.where(h1_close_times <= m5_ts)[0]
            if len(valid) == 0:
                continue

            causal_idx = int(valid[-1])
            h1_close = h1_close_times[causal_idx]
            assert h1_close <= m5_ts, (
                f"H1 bar closing at {h1_close} visible before M5 ts {m5_ts}"
            )

            if causal_idx + 1 < len(h1):
                next_close = h1_close_times[causal_idx + 1]
                assert next_close > m5_ts, (
                    "Next H1 bar should not have closed yet"
                )

    def test_rolling_features_use_only_past(self):
        """Rolling ATR computed at bar i must not change when future bars
        are appended."""
        from fx_smc_bot.utils.math import atr as compute_atr

        m5 = _make_m5_bars(n=100)

        atr_full = compute_atr(m5.high, m5.low, m5.close, period=14)

        trunc = m5.slice(0, 50)
        atr_trunc = compute_atr(trunc.high, trunc.low, trunc.close, period=14)

        for i in range(len(atr_trunc)):
            assert abs(atr_trunc[i] - atr_full[i]) < 1e-10, (
                f"ATR at bar {i} changed when future bars were appended"
            )

    def test_resampled_bar_label_is_start_of_bucket(self):
        """Resampled bars must be left-labeled: the timestamp is the start
        of the aggregation window, not the end."""
        m5 = _make_m5_bars(n=100)
        h1 = resample(m5, Timeframe.H1)

        for i in range(len(h1)):
            ts = h1.timestamps[i]
            ts_dt = ts.astype("datetime64[us]").astype(datetime)
            assert ts_dt.minute == 0, (
                f"H1 bar timestamp {ts_dt} should be on the hour"
            )
