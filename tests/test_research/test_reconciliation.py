"""Tests for paper-vs-backtest reconciliation."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from fx_smc_bot.config import Timeframe, TradingPair
from fx_smc_bot.domain import BacktestResult, ClosedTrade, Direction, EquityPoint, Position, SignalFamily
from fx_smc_bot.live.journal import JournalEvent
from fx_smc_bot.research.reconciliation import (
    ReconciliationReport,
    format_reconciliation_report,
    reconcile_paper_vs_backtest,
)


def _make_closed_trade(pnl: float, pair: TradingPair = TradingPair.EURUSD) -> ClosedTrade:
    pos = Position(
        pair=pair, direction=Direction.LONG,
        entry_price=1.1, stop_loss=1.097, take_profit=1.109, units=10000,
    )
    return ClosedTrade(
        position=pos,
        pair=pair, direction=Direction.LONG,
        family=SignalFamily.SWEEP_REVERSAL,
        entry_price=1.1, exit_price=1.1 + pnl / 10000,
        units=10000, pnl=pnl, pnl_pips=pnl / 10000 * 10000,
        opened_at=datetime(2024, 1, 1, 10), closed_at=datetime(2024, 1, 1, 12),
        duration_bars=8, reward_risk_ratio=2.0,
    )


def _make_backtest_result(trades: list[ClosedTrade]) -> BacktestResult:
    total_pnl = sum(t.pnl for t in trades)
    return BacktestResult(
        config_hash="test123",
        start_date=datetime(2024, 1, 1),
        end_date=datetime(2024, 12, 31),
        initial_capital=100_000,
        final_equity=100_000 + total_pnl,
        trades=trades,
        equity_curve=[],
    )


def _write_paper_journal(path: Path, total_trades: int, total_pnl: float, final_equity: float) -> None:
    events = [
        JournalEvent(
            event_type="run_complete",
            timestamp="2024-12-31T23:59:00",
            run_id="test_paper",
            data={
                "total_trades": total_trades,
                "total_pnl": total_pnl,
                "final_equity": final_equity,
            },
        )
    ]
    with open(path, "w") as f:
        for evt in events:
            f.write(evt.to_json() + "\n")


class TestReconciliation:
    def test_matching_results(self, tmp_path: Path) -> None:
        trades = [_make_closed_trade(100), _make_closed_trade(-50)]
        result = _make_backtest_result(trades)
        journal = tmp_path / "journal.jsonl"
        _write_paper_journal(journal, total_trades=2, total_pnl=50, final_equity=100_050)

        report = reconcile_paper_vs_backtest(result, journal)
        assert report.trade_count_diff == 0
        assert report.pnl_diff == pytest.approx(0.0, abs=1.0)

    def test_trade_count_mismatch(self, tmp_path: Path) -> None:
        trades = [_make_closed_trade(100)]
        result = _make_backtest_result(trades)
        journal = tmp_path / "journal.jsonl"
        _write_paper_journal(journal, total_trades=3, total_pnl=200, final_equity=100_200)

        report = reconcile_paper_vs_backtest(result, journal)
        assert report.trade_count_diff == 2
        assert any("mismatch" in n.lower() for n in report.notes)

    def test_pnl_divergence_flagged(self, tmp_path: Path) -> None:
        trades = [_make_closed_trade(1000)]
        result = _make_backtest_result(trades)
        journal = tmp_path / "journal.jsonl"
        _write_paper_journal(journal, total_trades=1, total_pnl=100, final_equity=100_100)

        report = reconcile_paper_vs_backtest(result, journal)
        assert abs(report.pnl_diff_pct) > 5
        assert any("divergence" in n.lower() for n in report.notes)

    def test_per_family_breakdown(self, tmp_path: Path) -> None:
        trades = [_make_closed_trade(100), _make_closed_trade(200)]
        result = _make_backtest_result(trades)
        journal = tmp_path / "journal.jsonl"
        _write_paper_journal(journal, total_trades=2, total_pnl=300, final_equity=100_300)

        report = reconcile_paper_vs_backtest(result, journal)
        assert "sweep_reversal" in report.per_family

    def test_empty_journal(self, tmp_path: Path) -> None:
        trades = [_make_closed_trade(100)]
        result = _make_backtest_result(trades)
        journal = tmp_path / "nonexistent.jsonl"

        report = reconcile_paper_vs_backtest(result, journal)
        assert report.paper_trade_count == 0


class TestFormatReport:
    def test_produces_markdown(self) -> None:
        report = ReconciliationReport(
            backtest_trade_count=10, paper_trade_count=12,
            trade_count_diff=2, backtest_pnl=5000, paper_pnl=4500,
            pnl_diff=-500, pnl_diff_pct=-10.0,
            backtest_equity=105_000, paper_equity=104_500,
            equity_diff=-500,
        )
        md = format_reconciliation_report(report)
        assert "# Paper vs Backtest Reconciliation" in md
        assert "10" in md
        assert "12" in md
