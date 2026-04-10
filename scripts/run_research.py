#!/usr/bin/env python3
"""Run a research experiment with walk-forward validation.

Usage:
    python scripts/run_research.py --config configs/base.yaml
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fx_smc_bot.backtesting.engine import BacktestEngine
from fx_smc_bot.config import AppConfig, Timeframe, TradingPair
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.research.experiments import load_config, save_experiment
from fx_smc_bot.research.reporting import summary_report
from fx_smc_bot.research.walk_forward import anchored_walk_forward
from fx_smc_bot.utils.logging import setup_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Run FX SMC research experiment")
    parser.add_argument("--config", type=str, default=None)
    parser.add_argument("--output-dir", type=str, default="artifacts/experiments")
    parser.add_argument("--label", type=str, default="research")
    args = parser.parse_args()

    setup_logging("INFO")
    logger = logging.getLogger(__name__)

    config = load_config(args.config) if args.config else AppConfig()

    # For demonstration, generate synthetic data
    from scripts.run_backtest import _generate_synthetic_data
    data = _generate_synthetic_data()

    logger.info("Running full backtest...")
    engine = BacktestEngine(config)
    result = engine.run(data)
    metrics = engine.metrics(result)

    report = summary_report(result, metrics)
    print(report)

    # Save results
    exp_dir = save_experiment(result, metrics, args.output_dir, args.label)
    logger.info("Results saved to %s", exp_dir)

    # Walk-forward analysis
    logger.info("Running walk-forward analysis...")
    for pair, series in data.items():
        n = len(series)
        if n < 300:
            logger.warning("Skipping walk-forward for %s (only %d bars)", pair.value, n)
            continue

        splits = anchored_walk_forward(n, n_folds=3, min_train_bars=150)
        for split in splits:
            test_slice = series.slice(split.test_start, split.test_end)
            fold_engine = BacktestEngine(config)
            fold_result = fold_engine.run({pair: test_slice})
            fold_metrics = fold_engine.metrics(fold_result)
            logger.info(
                "  %s fold %d: trades=%d sharpe=%.3f pf=%.2f",
                pair.value, split.fold_id, fold_metrics.total_trades,
                fold_metrics.sharpe_ratio, fold_metrics.profit_factor,
            )


if __name__ == "__main__":
    main()
