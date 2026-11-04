"""Tests for dashboard data preparation."""

from __future__ import annotations

import pandas as pd
import pytest

from fx_smc_bot.config import AppConfig, Timeframe
from fx_smc_bot.dashboard.service import (
    DashboardSnapshot,
    data_quality_frame,
    equity_frame,
    monthly_pnl_frame,
    pair_summary_frame,
    price_frame,
    run_snapshot,
    session_summary_frame,
    summary_rows,
    synthetic_market_data,
    trades_frame,
)


@pytest.fixture(scope="module")
def snapshot() -> DashboardSnapshot:
    data = synthetic_market_data(300)
    return run_snapshot(AppConfig(), data, source_label="test")


def test_synthetic_data_is_deterministic_and_ohlc_valid() -> None:
    first = synthetic_market_data(120)
    second = synthetic_market_data(120)

    assert set(first) == set(second)
    for pair, series in first.items():
        assert len(series) == 120
        assert (series.high >= series.low).all()
        assert (series.high >= series.open).all()
        assert (series.high >= series.close).all()
        assert (series.low <= series.open).all()
        assert (series.low <= series.close).all()
        assert (series.timestamps == second[pair].timestamps).all()


def test_snapshot_frames_have_stable_contract(snapshot: DashboardSnapshot) -> None:
    prices = price_frame(next(iter(snapshot.data.values())))
    trades = trades_frame(snapshot.result)
    equity = equity_frame(snapshot.result)
    summary = summary_rows(snapshot)

    assert list(prices.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert {"id", "pair", "direction", "family", "entry", "exit", "pnl"} <= set(trades.columns)
    assert {"timestamp", "equity", "drawdown_pct"} <= set(equity.columns)
    assert len(summary) == len(snapshot.data)
    assert snapshot.metrics.total_trades == len(snapshot.result.trades)
    assert pd.api.types.is_datetime64_any_dtype(prices["timestamp"])


def test_attribution_frames_reconcile_with_trade_pnl(snapshot: DashboardSnapshot) -> None:
    trades = trades_frame(snapshot.result)
    if trades.empty:
        pytest.skip("Synthetic run produced no closed trades")

    monthly = monthly_pnl_frame(trades)
    pairs = pair_summary_frame(trades)
    sessions = session_summary_frame(trades)

    assert list(monthly.columns) == ["month", "pnl", "trades", "win_rate"]
    assert list(pairs.columns) == ["pair", "trades", "win_rate", "pnl", "avg_pnl", "pips"]
    assert list(sessions.columns) == ["session", "trades", "win_rate", "pnl"]
    assert monthly["pnl"].sum() == pytest.approx(trades["pnl"].sum())
    assert pairs["pnl"].sum() == pytest.approx(trades["pnl"].sum())
    assert sessions["pnl"].sum() == pytest.approx(trades["pnl"].sum())
    assert pairs["trades"].sum() == len(trades)
    assert sessions["trades"].sum() == len(trades)
    assert monthly["win_rate"].between(0, 1).all()
    assert pairs["win_rate"].between(0, 1).all()


def test_data_quality_frame_contract(snapshot: DashboardSnapshot) -> None:
    quality = data_quality_frame(
        snapshot.data,
        expected_timeframe=Timeframe.M15,
    )

    assert list(quality.columns) == [
        "pair",
        "timeframe",
        "expected_timeframe",
        "timeframe_ok",
        "bars",
        "quality_score",
        "missing_bar_pct",
        "duplicates",
        "zero_range_bars",
        "stale_sequences",
        "issues",
    ]
    assert len(quality) == len(snapshot.data)
    assert quality["timeframe_ok"].all()
    assert quality["quality_score"].between(0, 1).all()
    assert (quality["missing_bar_pct"] >= 0).all()
    assert (quality["duplicates"] >= 0).all()
    assert quality["issues"].map(lambda value: isinstance(value, str)).all()
