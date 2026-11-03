"""Tests for dashboard data preparation."""

from __future__ import annotations

import pandas as pd

from fx_smc_bot.config import AppConfig
from fx_smc_bot.dashboard.service import (
    equity_frame,
    price_frame,
    run_snapshot,
    summary_rows,
    synthetic_market_data,
    trades_frame,
)


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


def test_snapshot_frames_have_stable_contract() -> None:
    data = synthetic_market_data(300)
    snapshot = run_snapshot(AppConfig(), data, source_label="test")

    prices = price_frame(next(iter(data.values())))
    trades = trades_frame(snapshot.result)
    equity = equity_frame(snapshot.result)
    summary = summary_rows(snapshot)

    assert list(prices.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert {"id", "pair", "direction", "family", "entry", "exit", "pnl"} <= set(trades.columns)
    assert {"timestamp", "equity", "drawdown_pct"} <= set(equity.columns)
    assert len(summary) == len(data)
    assert snapshot.metrics.total_trades == len(snapshot.result.trades)
    assert pd.api.types.is_datetime64_any_dtype(prices["timestamp"])
