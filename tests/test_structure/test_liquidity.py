"""Tests for liquidity detection."""

from __future__ import annotations

from datetime import datetime

from fx_smc_bot.config import StructureConfig, TradingPair
from fx_smc_bot.domain import LiquidityLevelType, SwingPoint, SwingType
from fx_smc_bot.structure.liquidity import detect_equal_levels


class TestEqualLevels:
    def test_detects_equal_highs(self) -> None:
        swings = [
            SwingPoint(bar_index=5, price=1.1050, swing_type=SwingType.HIGH,
                       timestamp=datetime(2024, 1, 2)),
            SwingPoint(bar_index=15, price=1.1051, swing_type=SwingType.HIGH,
                       timestamp=datetime(2024, 1, 2, 1)),
            SwingPoint(bar_index=25, price=1.1049, swing_type=SwingType.HIGH,
                       timestamp=datetime(2024, 1, 2, 2)),
        ]
        cfg = StructureConfig(equal_level_tolerance_pips=3.0, equal_level_min_touches=2)
        levels = detect_equal_levels(swings, TradingPair.EURUSD, cfg)
        eq_highs = [l for l in levels if l.level_type == LiquidityLevelType.EQUAL_HIGHS]
        assert len(eq_highs) == 1
        assert eq_highs[0].touch_count == 3

    def test_no_cluster_when_spread(self) -> None:
        swings = [
            SwingPoint(bar_index=5, price=1.1050, swing_type=SwingType.HIGH,
                       timestamp=datetime(2024, 1, 2)),
            SwingPoint(bar_index=15, price=1.1150, swing_type=SwingType.HIGH,
                       timestamp=datetime(2024, 1, 2, 1)),
        ]
        cfg = StructureConfig(equal_level_tolerance_pips=3.0, equal_level_min_touches=2)
        levels = detect_equal_levels(swings, TradingPair.EURUSD, cfg)
        assert len(levels) == 0

    def test_detects_equal_lows(self) -> None:
        swings = [
            SwingPoint(bar_index=10, price=1.0950, swing_type=SwingType.LOW,
                       timestamp=datetime(2024, 1, 2)),
            SwingPoint(bar_index=20, price=1.0952, swing_type=SwingType.LOW,
                       timestamp=datetime(2024, 1, 2, 1)),
        ]
        cfg = StructureConfig(equal_level_tolerance_pips=3.0, equal_level_min_touches=2)
        levels = detect_equal_levels(swings, TradingPair.EURUSD, cfg)
        eq_lows = [l for l in levels if l.level_type == LiquidityLevelType.EQUAL_LOWS]
        assert len(eq_lows) == 1
