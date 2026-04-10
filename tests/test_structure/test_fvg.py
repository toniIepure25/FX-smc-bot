"""Tests for FVG detection."""

from __future__ import annotations

import numpy as np
from datetime import datetime, timedelta

from fx_smc_bot.config import StructureConfig, Timeframe, TradingPair
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.domain import Direction, MarketBar
from fx_smc_bot.structure.fvg import detect_fvg, update_fvg_fill


def _make_bullish_fvg_bars() -> BarSeries:
    """Create bars with a guaranteed bullish FVG.

    Bar 0: normal
    Bar 1: strong bullish displacement
    Bar 2: gap up (low > bar 0 high)
    """
    start = datetime(2024, 1, 2, 8, 0)
    bars = [
        MarketBar(pair=TradingPair.EURUSD, timeframe=Timeframe.M15,
                  timestamp=start, open=1.1000, high=1.1010,
                  low=1.0990, close=1.1005, bar_index=0),
        MarketBar(pair=TradingPair.EURUSD, timeframe=Timeframe.M15,
                  timestamp=start + timedelta(minutes=15),
                  open=1.1005, high=1.1060, low=1.1000,
                  close=1.1055, bar_index=1),
        MarketBar(pair=TradingPair.EURUSD, timeframe=Timeframe.M15,
                  timestamp=start + timedelta(minutes=30),
                  open=1.1055, high=1.1080, low=1.1040,
                  close=1.1070, bar_index=2),
    ]
    # FVG: bar[2].low (1.1040) > bar[0].high (1.1010) => gap from 1.1010 to 1.1040
    return BarSeries.from_bars(bars)


class TestFVGDetection:
    def test_detects_bullish_fvg(self) -> None:
        series = _make_bullish_fvg_bars()
        cfg = StructureConfig(fvg_min_atr_multiple=0.0)
        fvgs = detect_fvg(series.high, series.low, series.close, series.timestamps, cfg)
        bullish = [f for f in fvgs if f.direction == Direction.LONG]
        assert len(bullish) >= 1
        fvg = bullish[0]
        assert fvg.high > fvg.low
        assert fvg.bar_index == 1  # middle candle

    def test_min_atr_filter(self) -> None:
        series = _make_bullish_fvg_bars()
        cfg_strict = StructureConfig(fvg_min_atr_multiple=10.0)
        fvgs = detect_fvg(series.high, series.low, series.close, series.timestamps, cfg_strict)
        assert len(fvgs) == 0

    def test_too_few_bars(self) -> None:
        bars = [
            MarketBar(pair=TradingPair.EURUSD, timeframe=Timeframe.M15,
                      timestamp=datetime(2024, 1, 2), open=1.1, high=1.101,
                      low=1.099, close=1.1005, bar_index=0),
        ]
        series = BarSeries.from_bars(bars)
        fvgs = detect_fvg(series.high, series.low, series.close, series.timestamps)
        assert len(fvgs) == 0

    def test_fill_tracking(self) -> None:
        series = _make_bullish_fvg_bars()
        cfg = StructureConfig(fvg_min_atr_multiple=0.0)
        fvgs = detect_fvg(series.high, series.low, series.close, series.timestamps, cfg)
        if fvgs:
            updated = update_fvg_fill(fvgs, series.high, series.low, up_to_bar=2)
            for f in updated:
                assert 0.0 <= f.filled_pct <= 1.0
