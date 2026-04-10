"""Tests for BarSeries data model."""

from __future__ import annotations

import numpy as np
import pytest

from fx_smc_bot.config import Timeframe, TradingPair
from fx_smc_bot.data.models import BarSeries

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from conftest import make_bars


class TestBarSeries:
    def test_from_bars_roundtrip(self) -> None:
        bars = make_bars(n=20)
        series = BarSeries.from_bars(bars)
        assert len(series) == 20
        assert series.pair == TradingPair.EURUSD
        assert series.timeframe == Timeframe.M15
        roundtrip = series.to_bars()
        assert len(roundtrip) == 20
        assert abs(roundtrip[0].open - bars[0].open) < 1e-10

    def test_from_bars_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            BarSeries.from_bars([])

    def test_length_mismatch_raises(self) -> None:
        bars = make_bars(n=10)
        series = BarSeries.from_bars(bars)
        with pytest.raises(ValueError, match="length"):
            BarSeries(
                pair=series.pair, timeframe=series.timeframe,
                timestamps=series.timestamps,
                open=series.open[:5], high=series.high,
                low=series.low, close=series.close,
            )

    def test_slice(self) -> None:
        series = BarSeries.from_bars(make_bars(n=50))
        sliced = series.slice(10, 20)
        assert len(sliced) == 10
        assert np.array_equal(sliced.open, series.open[10:20])
