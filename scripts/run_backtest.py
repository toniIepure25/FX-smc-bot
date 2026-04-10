#!/usr/bin/env python3
"""Run a backtest from a config file.

Usage:
    python scripts/run_backtest.py --config configs/base.yaml --data-dir data/raw

Generates synthetic data if --data-dir is not provided (for development).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Ensure the src directory is on the path when running as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fx_smc_bot.backtesting.engine import BacktestEngine
from fx_smc_bot.config import AppConfig, Timeframe, TradingPair
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.data.providers.csv_provider import CsvProvider
from fx_smc_bot.research.experiments import load_config
from fx_smc_bot.research.reporting import summary_report
from fx_smc_bot.utils.logging import setup_logging


def _generate_synthetic_data() -> dict[TradingPair, BarSeries]:
    """Generate synthetic data for development/testing."""
    import numpy as np
    from datetime import datetime, timedelta

    from fx_smc_bot.domain import MarketBar

    rng = np.random.default_rng(42)
    pairs = [TradingPair.EURUSD, TradingPair.GBPUSD, TradingPair.USDJPY]
    base_prices = {TradingPair.EURUSD: 1.1000, TradingPair.GBPUSD: 1.2700, TradingPair.USDJPY: 148.0}
    volatilities = {TradingPair.EURUSD: 0.0012, TradingPair.GBPUSD: 0.0015, TradingPair.USDJPY: 0.15}

    data: dict[TradingPair, BarSeries] = {}
    n_bars = 500
    start = datetime(2024, 1, 2, 0, 0)
    delta = timedelta(minutes=15)

    for pair in pairs:
        bars: list[MarketBar] = []
        price = base_prices[pair]
        vol = volatilities[pair]
        for i in range(n_bars):
            ts = start + delta * i
            move = rng.normal(0, vol)
            open_ = price
            close = open_ + move
            high = max(open_, close) + abs(rng.normal(0, vol * 0.4))
            low = min(open_, close) - abs(rng.normal(0, vol * 0.4))
            bars.append(MarketBar(
                pair=pair, timeframe=Timeframe.M15, timestamp=ts,
                open=round(open_, 5), high=round(high, 5),
                low=round(low, 5), close=round(close, 5), bar_index=i,
            ))
            price = close
        data[pair] = BarSeries.from_bars(bars)

    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="Run FX SMC backtest")
    parser.add_argument("--config", type=str, default=None,
                        help="Path to YAML config file")
    parser.add_argument("--data-dir", type=str, default=None,
                        help="Path to market data directory (Parquet or CSV)")
    parser.add_argument("--output-dir", type=str, default=None,
                        help="Save run artifacts to this directory")
    parser.add_argument("--label", type=str, default="backtest",
                        help="Label for this experiment run")
    parser.add_argument("--log-level", type=str, default="INFO")
    args = parser.parse_args()

    setup_logging(args.log_level)
    logger = logging.getLogger(__name__)

    if args.config:
        config = load_config(args.config)
    else:
        config = AppConfig()

    if args.data_dir:
        data_path = Path(args.data_dir)
        # Try Parquet first, fall back to CSV
        has_parquet = any(data_path.rglob("*.parquet"))
        if has_parquet:
            from fx_smc_bot.data.providers.parquet_provider import ParquetProvider
            provider = ParquetProvider(data_path)
        else:
            provider = CsvProvider(data_path)
        data: dict[TradingPair, BarSeries] = {}
        for pair in config.data.primary_pairs:
            for tf in config.data.execution_timeframes:
                try:
                    data[pair] = provider.load(pair, tf)
                    break
                except (FileNotFoundError, ValueError):
                    continue
    else:
        logger.info("No data directory specified; using synthetic data")
        data = _generate_synthetic_data()

    logger.info("Running backtest with %d pairs...", len(data))
    engine = BacktestEngine(config)
    result = engine.run(data)
    metrics = engine.metrics(result)

    report = summary_report(result, metrics)
    print(report)

    if args.output_dir:
        from fx_smc_bot.research.reporting import save_run_artifacts
        config_dict = config.model_dump() if args.config else None
        artifact_dir = save_run_artifacts(
            result, metrics, args.output_dir,
            config_dict=config_dict, label=args.label,
        )
        logger.info("Artifacts saved to %s", artifact_dir)


if __name__ == "__main__":
    main()
