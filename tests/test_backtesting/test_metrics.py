"""Tests for performance metrics."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from fx_smc_bot.backtesting.metrics import compute_metrics
from fx_smc_bot.config import TradingPair
from fx_smc_bot.domain import (
    ClosedTrade,
    Direction,
    EquityPoint,
    Position,
    SignalFamily,
)


def _make_trade(pnl: float, pnl_pips: float = 0.0, rr: float = 1.0) -> ClosedTrade:
    return ClosedTrade(
        position=Position(),
        family=SignalFamily.SWEEP_REVERSAL,
        pair=TradingPair.EURUSD,
        direction=Direction.LONG,
        entry_price=1.1,
        exit_price=1.1 + (pnl / 100_000) if pnl >= 0 else 1.1 - (abs(pnl) / 100_000),
        units=100_000,
        pnl=pnl,
        pnl_pips=pnl_pips,
        opened_at=datetime(2024, 1, 2),
        closed_at=datetime(2024, 1, 2, 4),
        duration_bars=16,
        reward_risk_ratio=rr,
    )


def _make_equity_curve(
    n: int = 50,
    initial: float = 100_000,
    drift: float = 50.0,
) -> list[EquityPoint]:
    points: list[EquityPoint] = []
    eq = initial
    peak = initial
    for i in range(n):
        eq += drift
        if eq > peak:
            peak = eq
        dd = peak - eq
        dd_pct = dd / peak if peak > 0 else 0.0
        points.append(EquityPoint(
            timestamp=datetime(2024, 1, 2) + timedelta(hours=i),
            equity=eq, cash=eq, unrealized_pnl=0.0,
            drawdown=dd, drawdown_pct=dd_pct,
        ))
    return points


class TestMetrics:
    def test_basic_metrics(self) -> None:
        trades = [_make_trade(500), _make_trade(-200), _make_trade(300)]
        equity = _make_equity_curve(n=50)
        metrics = compute_metrics(trades, equity)
        assert metrics.total_trades == 3
        assert metrics.winning_trades == 2
        assert metrics.losing_trades == 1
        assert metrics.win_rate == pytest.approx(2 / 3, abs=0.01)
        assert metrics.total_pnl == pytest.approx(600, abs=0.01)
        assert metrics.profit_factor > 1.0

    def test_all_winners(self) -> None:
        trades = [_make_trade(100) for _ in range(5)]
        equity = _make_equity_curve(n=50)
        metrics = compute_metrics(trades, equity)
        assert metrics.win_rate == 1.0
        assert metrics.profit_factor == float("inf")

    def test_empty_trades(self) -> None:
        metrics = compute_metrics([], [])
        assert metrics.total_trades == 0
        assert metrics.sharpe_ratio == 0.0
