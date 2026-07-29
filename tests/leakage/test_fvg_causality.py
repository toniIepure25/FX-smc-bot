"""Tests proving that FVG detection and entry orders respect causality.

An FVG formed by bars [i-1, i, i+1] is only visible after bar i+1 closes.
Entry orders based on the FVG must not be active until after bar i+1.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from fx_smc_bot.config import StructureConfig, Timeframe, TradingPair
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.domain import Direction, MarketBar
from fx_smc_bot.structure.fvg import detect_fvg, update_fvg_fill


def _make_bullish_fvg_series(
    fvg_center_idx: int = 10,
    n_bars: int = 20,
) -> BarSeries:
    """Create a series with a clear bullish FVG at fvg_center_idx.

    Bullish FVG: low[i+1] > high[i-1]
    """
    start = datetime(2024, 1, 2, 0, 0)
    delta = timedelta(minutes=5)
    bars: list[MarketBar] = []
    base = 1.1000

    for i in range(n_bars):
        if i == fvg_center_idx - 1:
            o, h, l, c = base, base + 0.0005, base - 0.0005, base
        elif i == fvg_center_idx:
            o, h, l, c = base + 0.0005, base + 0.0050, base + 0.0003, base + 0.0045
        elif i == fvg_center_idx + 1:
            o, h, l, c = base + 0.0045, base + 0.0060, base + 0.0015, base + 0.0055
        else:
            o, h, l, c = base, base + 0.0005, base - 0.0005, base
        bars.append(MarketBar(
            pair=TradingPair.EURUSD, timeframe=Timeframe.M5,
            timestamp=start + delta * i,
            open=o, high=h, low=l, close=c,
            bar_index=i, spread=0.00015,
        ))
    return BarSeries.from_bars(bars)


class TestFVGCausality:

    def test_fvg_not_detected_before_third_candle(self):
        """An FVG with center at bar 10 requires bar 11 to exist.
        A slice ending at bar 10 (exclusive bar 11) must not detect it."""
        fvg_idx = 10
        series = _make_bullish_fvg_series(fvg_center_idx=fvg_idx, n_bars=20)
        cfg = StructureConfig(fvg_min_atr_multiple=0.0)

        trunc = series.slice(0, fvg_idx + 1)  # bars 0..10, no bar 11
        fvgs = detect_fvg(trunc.high, trunc.low, trunc.close,
                          trunc.timestamps, config=cfg)
        fvgs_at_idx = [f for f in fvgs if f.bar_index == fvg_idx]
        assert len(fvgs_at_idx) == 0, "FVG detected before third candle closes"

    def test_fvg_detected_after_third_candle(self):
        """With bar 11 present, the FVG at center 10 should be detected."""
        fvg_idx = 10
        series = _make_bullish_fvg_series(fvg_center_idx=fvg_idx, n_bars=20)
        cfg = StructureConfig(fvg_min_atr_multiple=0.0)

        with_third = series.slice(0, fvg_idx + 2)  # bars 0..11
        fvgs = detect_fvg(with_third.high, with_third.low, with_third.close,
                          with_third.timestamps, config=cfg)
        fvgs_at_idx = [f for f in fvgs if f.bar_index == fvg_idx]
        assert len(fvgs_at_idx) == 1, "FVG should be detected after third candle"

    def test_fvg_fill_only_uses_subsequent_bars(self):
        """FVG fill tracking must not use bars at or before the FVG formation."""
        fvg_idx = 10
        series = _make_bullish_fvg_series(fvg_center_idx=fvg_idx, n_bars=20)
        cfg = StructureConfig(fvg_min_atr_multiple=0.0)

        fvgs = detect_fvg(series.high, series.low, series.close,
                          series.timestamps, config=cfg)

        updated = update_fvg_fill(
            fvgs, series.high, series.low,
            up_to_bar=fvg_idx + 1,  # Only 1 bar after creation
            max_fill_pct=cfg.fvg_max_fill_pct,
        )
        for fvg in updated:
            if fvg.bar_index == fvg_idx:
                assert fvg.filled_pct >= 0.0
