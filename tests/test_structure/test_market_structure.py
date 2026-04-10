"""Tests for BOS / CHoCH detection."""

from __future__ import annotations

from fx_smc_bot.config import StructureConfig
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.domain import BreakType, Direction
from fx_smc_bot.structure.market_structure import current_regime, detect_structure_breaks
from fx_smc_bot.structure.swings import detect_swings
from fx_smc_bot.domain import StructureRegime

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from conftest import make_trending_bars, make_bars


class TestStructureBreaks:
    def test_trending_up_produces_bullish_breaks(self) -> None:
        bars = make_trending_bars(n=80, direction="up", seed=42)
        series = BarSeries.from_bars(bars)
        cfg = StructureConfig(swing_lookback=3, min_swing_atr_multiple=0.0)
        swings = detect_swings(series.high, series.low, series.close, series.timestamps, cfg)
        breaks = detect_structure_breaks(swings, series.close, series.timestamps)
        bullish = [b for b in breaks if b.direction == Direction.LONG]
        assert len(bullish) > 0

    def test_trending_down_produces_bearish_breaks(self) -> None:
        bars = make_trending_bars(n=80, direction="down", seed=42)
        series = BarSeries.from_bars(bars)
        cfg = StructureConfig(swing_lookback=3, min_swing_atr_multiple=0.0)
        swings = detect_swings(series.high, series.low, series.close, series.timestamps, cfg)
        breaks = detect_structure_breaks(swings, series.close, series.timestamps)
        bearish = [b for b in breaks if b.direction == Direction.SHORT]
        assert len(bearish) > 0

    def test_current_regime_from_breaks(self) -> None:
        bars = make_trending_bars(n=80, direction="up", seed=42)
        series = BarSeries.from_bars(bars)
        cfg = StructureConfig(swing_lookback=3, min_swing_atr_multiple=0.0)
        swings = detect_swings(series.high, series.low, series.close, series.timestamps, cfg)
        breaks = detect_structure_breaks(swings, series.close, series.timestamps)
        regime = current_regime(breaks)
        assert regime in (StructureRegime.BULLISH, StructureRegime.BEARISH, StructureRegime.RANGING)

    def test_empty_swings_returns_empty(self) -> None:
        bars = make_bars(n=5)
        series = BarSeries.from_bars(bars)
        breaks = detect_structure_breaks([], series.close, series.timestamps)
        assert len(breaks) == 0

    def test_break_indices_are_valid(self) -> None:
        bars = make_bars(n=100, volatility=0.002, seed=77)
        series = BarSeries.from_bars(bars)
        cfg = StructureConfig(swing_lookback=3, min_swing_atr_multiple=0.0)
        swings = detect_swings(series.high, series.low, series.close, series.timestamps, cfg)
        breaks = detect_structure_breaks(swings, series.close, series.timestamps)
        for b in breaks:
            assert 0 <= b.break_bar_index < len(series)
            assert b.break_type in (BreakType.BOS, BreakType.CHOCH)
