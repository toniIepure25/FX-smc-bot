"""Tests proving that swing detection respects causal confirmation lag.

A fractal swing at pivot index i with lookback n is only confirmed at
bar i+n.  These tests verify that truncating the series to bar i+n-1
must NOT produce the swing at i.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from fx_smc_bot.config import StructureConfig, Timeframe, TradingPair
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.domain import MarketBar, SwingType
from fx_smc_bot.structure.swings import detect_swings


def _make_peak_at(
    peak_idx: int,
    n_bars: int,
    lookback: int = 5,
    pair: TradingPair = TradingPair.EURUSD,
) -> BarSeries:
    """Create a series with a clear swing high at peak_idx.
    The peak is 1.1200 and all surrounding bars are at 1.1000.
    """
    start = datetime(2024, 1, 2, 0, 0)
    delta = timedelta(minutes=5)
    bars: list[MarketBar] = []
    for i in range(n_bars):
        if i == peak_idx:
            price = 1.1200
        else:
            price = 1.1000
        bars.append(MarketBar(
            pair=pair, timeframe=Timeframe.M5, timestamp=start + delta * i,
            open=price - 0.0001, high=price + 0.0005,
            low=price - 0.0005, close=price,
            bar_index=i, spread=0.00015,
        ))
    return BarSeries.from_bars(bars)


class TestSwingCausality:

    def test_swing_not_detected_before_confirmation(self):
        """A swing high at index 15 with lookback=5 requires bar 20.
        Truncating to bar 19 must not detect the swing."""
        lookback = 5
        peak_idx = 15
        cfg = StructureConfig(swing_lookback=lookback, min_swing_atr_multiple=0.0)

        full = _make_peak_at(peak_idx, n_bars=30, lookback=lookback)
        truncated = full.slice(0, peak_idx + lookback)  # bars [0, 20) = up to bar 19

        swings_trunc = detect_swings(
            truncated.high, truncated.low, truncated.close,
            truncated.timestamps, config=cfg,
        )
        swing_highs_at_peak = [
            s for s in swings_trunc
            if s.swing_type == SwingType.HIGH and s.bar_index == peak_idx
        ]
        assert len(swing_highs_at_peak) == 0, (
            "Swing detected before confirmation bar"
        )

    def test_swing_detected_at_confirmation_bar(self):
        """With lookback=5, a swing at index 15 should be detectable
        when the series includes bar 20."""
        lookback = 5
        peak_idx = 15
        cfg = StructureConfig(swing_lookback=lookback, min_swing_atr_multiple=0.0)

        full = _make_peak_at(peak_idx, n_bars=30, lookback=lookback)
        at_confirm = full.slice(0, peak_idx + lookback + 1)  # bars [0, 21) = up to bar 20

        swings = detect_swings(
            at_confirm.high, at_confirm.low, at_confirm.close,
            at_confirm.timestamps, config=cfg,
        )
        swing_highs_at_peak = [
            s for s in swings
            if s.swing_type == SwingType.HIGH and s.bar_index == peak_idx
        ]
        assert len(swing_highs_at_peak) == 1, (
            "Swing should be detected at confirmation bar"
        )

    def test_appending_future_bar_does_not_change_past_swings(self):
        """After confirming swings up to bar N, adding bar N+1 must not
        change swings at indices < N-lookback."""
        lookback = 5
        cfg = StructureConfig(swing_lookback=lookback, min_swing_atr_multiple=0.0)

        full = _make_peak_at(15, n_bars=40, lookback=lookback)

        swings_at_25 = detect_swings(
            full.slice(0, 26).high, full.slice(0, 26).low,
            full.slice(0, 26).close, full.slice(0, 26).timestamps,
            config=cfg,
        )

        swings_at_30 = detect_swings(
            full.slice(0, 31).high, full.slice(0, 31).low,
            full.slice(0, 31).close, full.slice(0, 31).timestamps,
            config=cfg,
        )

        old_swings = [s for s in swings_at_25 if s.bar_index <= 20]
        new_swings = [s for s in swings_at_30 if s.bar_index <= 20]
        assert len(old_swings) == len(new_swings), (
            "Past swings should not change when future bars are added"
        )
        for s1, s2 in zip(old_swings, new_swings):
            assert s1.bar_index == s2.bar_index
            assert s1.price == s2.price
            assert s1.swing_type == s2.swing_type
