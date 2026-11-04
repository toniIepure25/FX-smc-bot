"""Tests for the shared backtest runner."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from fx_smc_bot.backtesting.runner import (
    load_market_data,
    run_backtest,
    synthetic_market_data,
)
from fx_smc_bot.config import AppConfig, Timeframe, TradingPair


def test_synthetic_market_data_is_deterministic() -> None:
    first = synthetic_market_data(120, seed=7)
    second = synthetic_market_data(120, seed=7)

    assert set(first) == set(second)
    for pair in first:
        assert first[pair].timeframe is Timeframe.M15
        np.testing.assert_array_equal(first[pair].close, second[pair].close)
        assert len(first[pair]) == 120


def test_synthetic_market_data_rejects_invalid_input() -> None:
    with pytest.raises(ValueError, match="at least 50"):
        synthetic_market_data(10)
    with pytest.raises(ValueError, match="No synthetic specification"):
        synthetic_market_data(60, pairs=[TradingPair.EURJPY])


def test_load_market_data_rejects_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="does not exist"):
        load_market_data(tmp_path / "missing", AppConfig())


def test_load_market_data_falls_back_across_providers(tmp_path: Path) -> None:
    import pandas as pd

    for pair, series in synthetic_market_data(120).items():
        pair_dir = tmp_path / pair.value
        pair_dir.mkdir(parents=True)
        frame = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(series.timestamps),
                "open": series.open,
                "high": series.high,
                "low": series.low,
                "close": series.close,
            }
        )
        if pair is TradingPair.EURUSD:
            frame.to_parquet(pair_dir / f"{Timeframe.M15.value}.parquet", index=False)
        else:
            frame.to_csv(pair_dir / f"{Timeframe.M15.value}.csv", index=False)

    data = load_market_data(tmp_path, AppConfig())

    assert set(data) == {TradingPair.EURUSD, TradingPair.GBPUSD, TradingPair.USDJPY}
    assert all(series.timeframe is Timeframe.M15 for series in data.values())


def test_run_backtest_returns_result_and_metrics() -> None:
    data = synthetic_market_data(500)
    run = run_backtest(AppConfig(), data)

    assert run.data is data
    assert run.result.final_equity > 0
    assert run.result.trades
    assert run.metrics.total_trades == len(run.result.trades)


def test_run_backtest_rejects_empty_data() -> None:
    with pytest.raises(ValueError, match="No market data"):
        run_backtest(AppConfig(), {})
