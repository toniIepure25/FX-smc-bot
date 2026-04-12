"""Tests for the ValidationCampaign orchestrator."""

from __future__ import annotations

import numpy as np
import pytest
from unittest.mock import MagicMock, patch

from fx_smc_bot.config import AppConfig, TradingPair, Timeframe
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.research.frozen_config import (
    DataSplitPolicy,
    freeze_config,
    split_data,
)
from fx_smc_bot.research.validation import (
    CandidateRun,
    ValidationCampaign,
    ValidationStage,
)


def _make_series(n: int = 500) -> dict[TradingPair, BarSeries]:
    ts = np.arange(
        np.datetime64("2023-01-01"), np.datetime64("2023-01-01") + np.timedelta64(n, "h"),
        np.timedelta64(1, "h"),
    )[:n]
    prices = np.cumsum(np.random.default_rng(42).standard_normal(n) * 0.001) + 1.1
    series = BarSeries(
        pair=TradingPair.EURUSD, timeframe=Timeframe.H1,
        timestamps=ts,
        open=prices, high=prices + 0.001, low=prices - 0.001, close=prices,
    )
    return {TradingPair.EURUSD: series}


class TestValidationStage:
    def test_all_stages_defined(self) -> None:
        stages = [s.value for s in ValidationStage]
        assert "exploratory" in stages
        assert "holdout" in stages
        assert "decided" in stages


def _make_perf(**overrides) -> "PerformanceSummary":
    from fx_smc_bot.backtesting.metrics import PerformanceSummary
    defaults = dict(
        total_trades=50, winning_trades=27, losing_trades=23, win_rate=0.54,
        avg_pnl=20.0, avg_winner=50.0, avg_loser=-30.0, profit_factor=1.5,
        expectancy=20.0, expectancy_pips=2.0, avg_rr_ratio=1.67,
        total_pnl=1000.0, max_drawdown=200.0, max_drawdown_pct=0.02,
        sharpe_ratio=1.2, sortino_ratio=1.5, calmar_ratio=2.0,
        annualized_return=0.1, total_days=365.0,
    )
    defaults.update(overrides)
    return PerformanceSummary(**defaults)


class TestCandidateRun:
    def test_to_dict_minimal(self) -> None:
        fc = freeze_config(AppConfig(), label="test")
        run = CandidateRun(candidate=fc, stage=ValidationStage.FROZEN_EVAL)
        d = run.to_dict()
        assert d["label"] == "test"
        assert d["stage"] == "frozen_eval"
        assert "metrics" not in d

    def test_to_dict_with_metrics(self) -> None:
        fc = freeze_config(AppConfig(), label="test")
        metrics = _make_perf(sharpe_ratio=1.2, total_trades=50)
        run = CandidateRun(candidate=fc, stage=ValidationStage.FROZEN_EVAL, metrics=metrics)
        d = run.to_dict()
        assert d["metrics"]["sharpe_ratio"] == 1.2
        assert d["metrics"]["total_trades"] == 50


class TestValidationCampaign:
    def test_init(self) -> None:
        data = _make_series()
        fc = freeze_config(AppConfig(), label="test")
        campaign = ValidationCampaign(candidates=[fc], data=data)
        assert campaign._candidates == [fc]

    def test_skips_invalid_hash(self) -> None:
        data = _make_series()
        fc = freeze_config(AppConfig(), label="test")
        fc.config.alpha.min_signal_score = 0.999  # Mutate to break hash
        campaign = ValidationCampaign(candidates=[fc], data=data)
        runs = campaign.run_full_evaluation()
        assert len(runs) == 0

    @patch("fx_smc_bot.research.validation.BacktestEngine")
    @patch("fx_smc_bot.research.validation.run_execution_stress")
    def test_full_evaluation_runs(self, mock_stress, mock_engine_cls) -> None:
        data = _make_series()
        fc = freeze_config(AppConfig(), label="test")

        mock_result = MagicMock()
        mock_result.trades = []
        mock_engine = MagicMock()
        mock_engine.run.return_value = mock_result
        mock_engine.metrics.return_value = _make_perf(
            total_trades=50, win_rate=0.5, profit_factor=1.2,
            sharpe_ratio=0.8, total_pnl=500.0, max_drawdown=100.0,
            max_drawdown_pct=0.01,
        )
        mock_engine_cls.return_value = mock_engine
        mock_stress.side_effect = Exception("no stress")

        campaign = ValidationCampaign(candidates=[fc], data=data)
        runs = campaign.run_full_evaluation()
        assert len(runs) == 1
        assert runs[0].metrics is not None
        assert runs[0].gate_result is not None

    @patch("fx_smc_bot.research.validation.BacktestEngine")
    def test_holdout_evaluation(self, mock_engine_cls) -> None:
        data = _make_series(n=1000)
        fc = freeze_config(AppConfig(), label="test")

        mock_result = MagicMock()
        mock_result.trades = []
        mock_engine = MagicMock()
        mock_engine.run.return_value = mock_result
        mock_engine.metrics.return_value = _make_perf(
            total_trades=20, win_rate=0.45, profit_factor=1.1,
            sharpe_ratio=0.5, total_pnl=200.0, max_drawdown=50.0,
            max_drawdown_pct=0.005,
        )
        mock_engine_cls.return_value = mock_engine

        campaign = ValidationCampaign(candidates=[fc], data=data)
        runs = campaign.run_holdout_evaluation([fc])
        assert len(runs) == 1
        assert runs[0].stage == ValidationStage.HOLDOUT
