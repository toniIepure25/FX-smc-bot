"""Tests for structured evaluation and cost sensitivity."""

from __future__ import annotations

from datetime import datetime

import pytest

from fx_smc_bot.backtesting.attribution import by_year, by_month
from fx_smc_bot.backtesting.metrics import PerformanceSummary
from fx_smc_bot.config import TradingPair
from fx_smc_bot.domain import (
    BacktestResult,
    ClosedTrade,
    Direction,
    Position,
    SessionName,
    SignalFamily,
)
from fx_smc_bot.research.evaluation import CostSensitivityPoint, evaluate


def _make_trade(
    pair: TradingPair = TradingPair.EURUSD,
    pnl: float = 100.0,
    year: int = 2024,
    month: int = 3,
) -> ClosedTrade:
    return ClosedTrade(
        position=Position(),
        family=SignalFamily.SWEEP_REVERSAL,
        pair=pair,
        direction=Direction.LONG,
        entry_price=1.1000,
        exit_price=1.1010 if pnl > 0 else 1.0990,
        units=100_000,
        pnl=pnl,
        pnl_pips=pnl / 10,
        opened_at=datetime(year, month, 15, 10, 0),
        closed_at=datetime(year, month, 15, 14, 0),
        duration_bars=16,
        reward_risk_ratio=2.0 if pnl > 0 else 0.5,
        session=SessionName.LONDON,
    )


@pytest.fixture
def sample_trades() -> list[ClosedTrade]:
    return [
        _make_trade(pnl=200, year=2023, month=6),
        _make_trade(pnl=-50, year=2023, month=9),
        _make_trade(pair=TradingPair.GBPUSD, pnl=150, year=2024, month=1),
        _make_trade(pnl=-100, year=2024, month=4),
        _make_trade(pnl=300, year=2024, month=7),
    ]


class TestByYear:
    def test_groups_by_year(self, sample_trades: list[ClosedTrade]) -> None:
        slices = by_year(sample_trades)
        labels = [s.label for s in slices]
        assert "2023" in labels
        assert "2024" in labels

    def test_trade_counts_per_year(self, sample_trades: list[ClosedTrade]) -> None:
        slices = by_year(sample_trades)
        year_2023 = next(s for s in slices if s.label == "2023")
        year_2024 = next(s for s in slices if s.label == "2024")
        assert year_2023.trade_count == 2
        assert year_2024.trade_count == 3


class TestByMonth:
    def test_groups_by_month(self, sample_trades: list[ClosedTrade]) -> None:
        slices = by_month(sample_trades)
        assert any(s.label == "2024-01" for s in slices)


class TestEvaluate:
    def test_evaluation_report_structure(self, sample_trades: list[ClosedTrade]) -> None:
        result = BacktestResult(
            config_hash="test", start_date=datetime(2023, 1, 1),
            end_date=datetime(2024, 12, 31), initial_capital=100_000,
            final_equity=100_500, trades=sample_trades,
        )
        metrics = PerformanceSummary(
            total_trades=5, winning_trades=3, losing_trades=2,
            win_rate=0.6, avg_pnl=100, avg_winner=216.67, avg_loser=-75,
            profit_factor=4.33, expectancy=100, expectancy_pips=10,
            avg_rr_ratio=1.5, total_pnl=500, max_drawdown=100,
            max_drawdown_pct=0.001, sharpe_ratio=1.5, sortino_ratio=2.0,
            calmar_ratio=3.0, annualized_return=0.05, total_days=365,
        )
        report = evaluate(result, metrics)
        assert report.overall.total_trades == 5
        assert len(report.by_year) >= 2
        assert len(report.by_pair) >= 1
