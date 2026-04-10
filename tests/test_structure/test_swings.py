"""Tests for swing detection."""

from __future__ import annotations

import numpy as np

from fx_smc_bot.config import StructureConfig
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.domain import SwingType
from fx_smc_bot.structure.swings import detect_swings

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from conftest import make_swing_pattern_bars, make_bars, make_trending_bars


class TestSwingDetection:
    def test_detects_swings_in_pattern(self) -> None:
        bars = make_swing_pattern_bars()
        series = BarSeries.from_bars(bars)
        cfg = StructureConfig(swing_lookback=3, min_swing_atr_multiple=0.0)
        swings = detect_swings(series.high, series.low, series.close, series.timestamps, cfg)
        assert len(swings) > 0
        highs = [s for s in swings if s.swing_type == SwingType.HIGH]
        lows = [s for s in swings if s.swing_type == SwingType.LOW]
        assert len(highs) >= 1
        assert len(lows) >= 1

    def test_swing_prices_are_reasonable(self) -> None:
        bars = make_swing_pattern_bars()
        series = BarSeries.from_bars(bars)
        cfg = StructureConfig(swing_lookback=3, min_swing_atr_multiple=0.0)
        swings = detect_swings(series.high, series.low, series.close, series.timestamps, cfg)
        for s in swings:
            if s.swing_type == SwingType.HIGH:
                assert s.price >= 1.09
            else:
                assert s.price <= 1.12

    def test_lookback_affects_count(self) -> None:
        bars = make_bars(n=100, volatility=0.0015, seed=123)
        series = BarSeries.from_bars(bars)
        cfg_tight = StructureConfig(swing_lookback=2, min_swing_atr_multiple=0.0)
        cfg_wide = StructureConfig(swing_lookback=8, min_swing_atr_multiple=0.0)
        swings_tight = detect_swings(series.high, series.low, series.close, series.timestamps, cfg_tight)
        swings_wide = detect_swings(series.high, series.low, series.close, series.timestamps, cfg_wide)
        assert len(swings_tight) >= len(swings_wide)

    def test_too_few_bars_returns_empty(self) -> None:
        bars = make_bars(n=5)
        series = BarSeries.from_bars(bars)
        cfg = StructureConfig(swing_lookback=5, min_swing_atr_multiple=0.0)
        swings = detect_swings(series.high, series.low, series.close, series.timestamps, cfg)
        assert len(swings) == 0

    def test_strength_is_positive(self) -> None:
        bars = make_bars(n=80, seed=99)
        series = BarSeries.from_bars(bars)
        cfg = StructureConfig(swing_lookback=3, min_swing_atr_multiple=0.0)
        swings = detect_swings(series.high, series.low, series.close, series.timestamps, cfg)
        for s in swings:
            assert s.strength >= 1
