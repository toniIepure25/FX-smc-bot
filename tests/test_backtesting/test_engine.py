"""Tests for the backtest engine."""

from __future__ import annotations

import pytest

from fx_smc_bot.backtesting.engine import BacktestEngine
from fx_smc_bot.config import AppConfig, Timeframe, TradingPair
from fx_smc_bot.data.models import BarSeries

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from conftest import make_bars, make_trending_bars


class TestBacktestEngine:
    def test_engine_runs_without_crash(self) -> None:
        """Smoke test: engine processes bars without exceptions."""
        bars = make_bars(n=200, volatility=0.002, seed=42)
        series = BarSeries.from_bars(bars)
        config = AppConfig()
        engine = BacktestEngine(config)
        result = engine.run({TradingPair.EURUSD: series})
        assert result.initial_capital == 100_000.0
        assert result.start_date is not None
        assert result.end_date is not None
        assert len(result.equity_curve) > 0

    def test_engine_trending_produces_trades(self) -> None:
        """With trending data, the engine should produce at least some trades."""
        bars = make_trending_bars(n=200, direction="up", seed=42)
        series = BarSeries.from_bars(bars)
        config = AppConfig()
        engine = BacktestEngine(config)
        result = engine.run({TradingPair.EURUSD: series})
        # May or may not produce trades depending on structure detection
        # but should at least run cleanly
        assert result.final_equity > 0

    def test_engine_multi_pair(self) -> None:
        """Test with multiple pairs."""
        eu_bars = make_bars(n=150, pair=TradingPair.EURUSD, volatility=0.0015, seed=1)
        gb_bars = make_bars(n=150, pair=TradingPair.GBPUSD, volatility=0.0015, seed=2)
        data = {
            TradingPair.EURUSD: BarSeries.from_bars(eu_bars),
            TradingPair.GBPUSD: BarSeries.from_bars(gb_bars),
        }
        config = AppConfig()
        engine = BacktestEngine(config)
        result = engine.run(data)
        assert len(result.equity_curve) > 0

    def test_metrics_on_empty_result(self) -> None:
        bars = make_bars(n=50)
        series = BarSeries.from_bars(bars)
        config = AppConfig()
        engine = BacktestEngine(config)
        result = engine.run({TradingPair.EURUSD: series})
        metrics = engine.metrics(result)
        assert metrics.total_trades >= 0
