"""Reusable backtest orchestration shared by the CLI, dashboard and scripts.

The engine itself is intentionally unaware of files, demos or presentation.
This module owns the small amount of plumbing needed to go from a config and a
data directory to a completed run, so command-line entry points do not
reimplement provider selection or synthetic-data generation.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from fx_smc_bot.backtesting.engine import BacktestEngine
from fx_smc_bot.backtesting.metrics import PerformanceSummary
from fx_smc_bot.config import TIMEFRAME_MINUTES, AppConfig, Timeframe, TradingPair
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.domain import BacktestResult, MarketBar


@dataclass(frozen=True)
class BacktestRun:
    """A completed backtest with the data and config that produced it."""

    config: AppConfig
    data: dict[TradingPair, BarSeries]
    result: BacktestResult
    metrics: PerformanceSummary


# Pair-specific starting prices and per-bar volatility for the deterministic demo.
# These are presentation fixtures, not calibrated market parameters.
_SYNTHETIC_SPECS: dict[TradingPair, tuple[float, float]] = {
    TradingPair.EURUSD: (1.1000, 0.0012),
    TradingPair.GBPUSD: (1.2700, 0.0015),
    TradingPair.USDJPY: (148.0, 0.15),
}


def synthetic_market_data(
    n_bars: int = 1500,
    *,
    timeframe: Timeframe = Timeframe.M15,
    seed: int = 42,
    pairs: Iterable[TradingPair] | None = None,
) -> dict[TradingPair, BarSeries]:
    """Generate deterministic synthetic bars for the self-contained demo."""
    if n_bars < 50:
        raise ValueError("n_bars must be at least 50")

    rng = np.random.default_rng(seed)
    selected = list(pairs or _SYNTHETIC_SPECS)
    unsupported = [pair for pair in selected if pair not in _SYNTHETIC_SPECS]
    if unsupported:
        names = ", ".join(pair.value for pair in unsupported)
        raise ValueError(f"No synthetic specification for: {names}")
    start = datetime(2024, 1, 2, 0, 0)
    delta = timedelta(minutes=TIMEFRAME_MINUTES[timeframe])

    data: dict[TradingPair, BarSeries] = {}
    for pair in selected:
        base, volatility = _SYNTHETIC_SPECS[pair]
        price = base
        bars: list[MarketBar] = []
        for index in range(n_bars):
            move = rng.normal(0, volatility)
            open_price = price
            close_price = open_price + move
            high = max(open_price, close_price) + abs(rng.normal(0, volatility * 0.4))
            low = min(open_price, close_price) - abs(rng.normal(0, volatility * 0.4))
            bars.append(
                MarketBar(
                    pair=pair,
                    timeframe=timeframe,
                    timestamp=start + delta * index,
                    open=round(open_price, 5),
                    high=round(high, 5),
                    low=round(low, 5),
                    close=round(close_price, 5),
                    bar_index=index,
                    volume=float(rng.integers(80, 1200)),
                )
            )
            price = close_price
        data[pair] = BarSeries.from_bars(bars)

    return data


def load_market_data(data_dir: str | Path, config: AppConfig) -> dict[TradingPair, BarSeries]:
    """Load the configured execution timeframe for every available pair."""
    path = Path(data_dir)
    if not path.exists():
        raise FileNotFoundError(f"Data directory does not exist: {path}")

    providers: list[Any] = []
    if any(path.rglob("*.parquet")):
        from fx_smc_bot.data.providers.parquet_provider import ParquetProvider

        providers.append(ParquetProvider(path))
    from fx_smc_bot.data.providers.csv_provider import CsvProvider

    providers.append(CsvProvider(path))

    data: dict[TradingPair, BarSeries] = {}
    for pair in config.data.primary_pairs:
        for timeframe in config.data.execution_timeframes:
            loaded = False
            for provider in providers:
                try:
                    data[pair] = provider.load(pair, timeframe)
                    loaded = True
                    break
                except (FileNotFoundError, ValueError):
                    continue
            if loaded:
                break

    if not data:
        raise ValueError(f"No usable execution-timeframe data found under {path}")
    return data


def run_backtest(
    config: AppConfig,
    data: dict[TradingPair, BarSeries],
) -> BacktestRun:
    """Run one in-process backtest and return its result and metrics."""
    if not data:
        raise ValueError("No market data supplied")

    engine = BacktestEngine(config)
    result = engine.run(data)
    metrics = engine.metrics(result)
    return BacktestRun(config=config, data=data, result=result, metrics=metrics)
