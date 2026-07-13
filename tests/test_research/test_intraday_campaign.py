"""Tests for the intraday SMC campaign engine."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from fx_smc_bot.config import Timeframe, TradingPair
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.research.intraday_campaign import (
    CampaignResult,
    RunResult,
    StrategyRunConfig,
    _extract_daily_returns,
    run_single,
    save_campaign_results,
)


def _make_series(n: int = 200, pair: TradingPair = TradingPair.EURUSD) -> BarSeries:
    """Create a synthetic BarSeries for testing."""
    rng = np.random.default_rng(42)
    base = 1.1000
    closes = base + np.cumsum(rng.normal(0, 0.0003, n))
    opens = np.roll(closes, 1)
    opens[0] = base
    highs = np.maximum(opens, closes) + np.abs(rng.normal(0, 0.0002, n))
    lows = np.minimum(opens, closes) - np.abs(rng.normal(0, 0.0002, n))
    start = np.datetime64("2023-01-02T00:00", "ns")
    timestamps = np.array([start + np.timedelta64(i * 5, "m") for i in range(n)])
    return BarSeries(
        pair=pair,
        timeframe=Timeframe.M5,
        timestamps=timestamps,
        open=opens,
        high=highs,
        low=lows,
        close=closes,
    )


class TestStrategyRunConfig:
    def test_auto_label(self):
        cfg = StrategyRunConfig(
            family="sweep_reversal", pair=TradingPair.EURUSD, session="london",
        )
        assert cfg.label == "sweep_reversal/EURUSD/london"

    def test_ablation_label(self):
        cfg = StrategyRunConfig(
            family="sweep_reversal", pair=TradingPair.EURUSD,
            session="london", ablation="no_mss",
        )
        assert "no_mss" in cfg.label


class TestRunResult:
    def test_summary_dict(self):
        cfg = StrategyRunConfig(
            family="test", pair=TradingPair.EURUSD, session="london",
        )
        result = RunResult(
            config=cfg, trade_count=50, net_pnl=1234.56,
            sharpe=1.234, win_rate=0.55,
        )
        d = result.summary_dict()
        assert d["trade_count"] == 50
        assert d["net_pnl"] == 1234.56
        assert d["sharpe"] == 1.234
        assert d["pair"] == "EURUSD"

    def test_error_summary(self):
        cfg = StrategyRunConfig(
            family="test", pair=TradingPair.EURUSD, session="london",
        )
        result = RunResult(config=cfg, error="no data")
        d = result.summary_dict()
        assert d["error"] == "no data"
        assert d["trade_count"] == 0


class TestExtractDailyReturns:
    def test_empty_curve(self):
        rets = _extract_daily_returns([], 100_000)
        assert len(rets) == 0

    def test_single_point(self):
        from fx_smc_bot.domain import EquityPoint
        pts = [EquityPoint(
            timestamp=datetime(2023, 1, 2, 10, 0),
            equity=100_000, cash=100_000, unrealized_pnl=0,
            drawdown=0, drawdown_pct=0,
        )]
        rets = _extract_daily_returns(pts, 100_000)
        assert len(rets) == 0

    def test_multi_day(self):
        from fx_smc_bot.domain import EquityPoint
        pts = [
            EquityPoint(timestamp=datetime(2023, 1, 2, 17, 0), equity=100_000,
                        cash=100_000, unrealized_pnl=0, drawdown=0, drawdown_pct=0),
            EquityPoint(timestamp=datetime(2023, 1, 3, 17, 0), equity=101_000,
                        cash=101_000, unrealized_pnl=0, drawdown=0, drawdown_pct=0),
            EquityPoint(timestamp=datetime(2023, 1, 4, 17, 0), equity=100_500,
                        cash=100_500, unrealized_pnl=0, drawdown=0, drawdown_pct=0),
        ]
        rets = _extract_daily_returns(pts, 100_000)
        assert len(rets) == 2
        assert rets[0] == pytest.approx(0.01, abs=1e-6)
        assert rets[1] < 0


class TestRunSingle:
    def test_missing_pair(self):
        cfg = StrategyRunConfig(
            family="sweep_reversal", pair=TradingPair.USDJPY, session="london",
        )
        result = run_single(cfg, {})
        assert result.error is not None
        assert "No data" in result.error

    def test_runs_with_data(self):
        cfg = StrategyRunConfig(
            family="sweep_reversal", pair=TradingPair.EURUSD, session="london",
        )
        data = {TradingPair.EURUSD: _make_series(200)}
        result = run_single(cfg, data)
        assert result.error is None
        assert result.backtest_result is not None


class TestSaveCampaignResults:
    def test_save_and_load(self, tmp_path: Path):
        campaign = CampaignResult(
            run_id="test_001",
            timestamp="2023-01-01T00:00:00",
        )
        cfg = StrategyRunConfig(
            family="test", pair=TradingPair.EURUSD, session="london",
        )
        campaign.runs.append(RunResult(config=cfg, trade_count=10, net_pnl=500.0))

        path = save_campaign_results(campaign, tmp_path)
        assert path.exists()

        data = json.loads(path.read_text())
        assert data["run_id"] == "test_001"
        assert len(data["runs"]) == 1
        assert data["runs"][0]["trade_count"] == 10
