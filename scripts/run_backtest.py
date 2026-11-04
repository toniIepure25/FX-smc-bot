#!/usr/bin/env python3
"""Run a backtest from a config file.

Usage:
    python scripts/run_backtest.py --config configs/base.yaml --data-dir data/raw

Generates synthetic data if --data-dir is not provided (for development).
The reusable orchestration lives in ``fx_smc_bot.backtesting.runner`` so this
script and the CLI cannot drift apart.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Ensure the src directory is on the path when running as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fx_smc_bot.backtesting.runner import load_market_data, run_backtest, synthetic_market_data
from fx_smc_bot.config import AppConfig
from fx_smc_bot.research.experiments import load_config
from fx_smc_bot.research.reporting import save_run_artifacts, summary_report
from fx_smc_bot.utils.logging import setup_logging


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

    config = load_config(args.config) if args.config else AppConfig()

    if args.data_dir:
        data = load_market_data(args.data_dir, config)
    else:
        logger.info("No data directory specified; using synthetic data")
        data = synthetic_market_data(n_bars=500)

    logger.info("Running backtest with %d pairs...", len(data))
    run = run_backtest(config, data)
    print(summary_report(run.result, run.metrics))

    if args.output_dir:
        artifact_dir = save_run_artifacts(
            run.result,
            run.metrics,
            args.output_dir,
            config_dict=config.model_dump(),
            label=args.label,
        )
        logger.info("Artifacts saved to %s", artifact_dir)


if __name__ == "__main__":
    main()
