"""Tests for swap/financing cost calculation."""

from __future__ import annotations

from datetime import datetime

import pytest

from fx_smc_bot.config import TradingPair
from fx_smc_bot.execution.swap import SwapCalculator, SwapRate


class TestSwapCalculator:

    def test_long_negative_swap(self):
        """Long EURUSD should incur negative swap (cost)."""
        calc = SwapCalculator()
        swap = calc.daily_swap(TradingPair.EURUSD, "long", 100_000, day_of_week=0)
        assert swap < 0

    def test_short_positive_swap(self):
        """Short EURUSD should receive positive swap (credit)."""
        calc = SwapCalculator()
        swap = calc.daily_swap(TradingPair.EURUSD, "short", 100_000, day_of_week=0)
        assert swap > 0

    def test_triple_wednesday(self):
        """Wednesday swap should be 3x the normal rate."""
        calc = SwapCalculator()
        normal = calc.daily_swap(TradingPair.EURUSD, "long", 100_000, day_of_week=0)
        wednesday = calc.daily_swap(TradingPair.EURUSD, "long", 100_000, day_of_week=2)
        assert abs(wednesday - 3 * normal) < 1e-10

    def test_fractional_lots(self):
        """Swap scales proportionally with position size."""
        calc = SwapCalculator()
        full = calc.daily_swap(TradingPair.EURUSD, "long", 100_000, day_of_week=0)
        half = calc.daily_swap(TradingPair.EURUSD, "long", 50_000, day_of_week=0)
        assert abs(half - full / 2) < 1e-10

    def test_rollover_detection_same_day(self):
        calc = SwapCalculator()
        assert not calc.crosses_rollover(
            datetime(2024, 1, 15, 10, 0),
            datetime(2024, 1, 15, 15, 0),
        )

    def test_rollover_detection_cross_day(self):
        calc = SwapCalculator()
        assert calc.crosses_rollover(
            datetime(2024, 1, 15, 21, 0),
            datetime(2024, 1, 15, 23, 0),
        )

    def test_custom_rates(self):
        rates = {
            TradingPair.EURUSD: SwapRate(
                TradingPair.EURUSD, long_rate=-10.0, short_rate=5.0,
            ),
        }
        calc = SwapCalculator(rates=rates)
        swap = calc.daily_swap(TradingPair.EURUSD, "long", 100_000, day_of_week=0)
        assert swap == -10.0
