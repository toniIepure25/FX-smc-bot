#!/usr/bin/env python3
"""Paper trading CLI: replay real data through the paper broker with audit trail.

Usage:
    python scripts/run_paper.py --data-dir data/processed --output-dir paper_runs
    python scripts/run_paper.py --data-dir data/processed --config configs/base.yaml
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Paper trading replay")
    parser.add_argument("--data-dir", type=str, required=True, help="Path to processed Parquet data")
    parser.add_argument("--output-dir", type=str, default="paper_runs", help="Output directory for run artifacts")
    parser.add_argument("--config", type=str, default=None, help="YAML config override file")
    parser.add_argument("--pairs", nargs="+", default=None, help="Pairs to trade (e.g., EURUSD GBPUSD)")
    args = parser.parse_args()

    from fx_smc_bot.config import AppConfig, TradingPair
    from fx_smc_bot.data.providers.parquet_provider import ParquetProvider
    from fx_smc_bot.live.runner import PaperTradingRunner

    config_dict: dict = {}
    if args.config:
        with open(args.config) as f:
            config_dict = yaml.safe_load(f) or {}

    config = AppConfig(**config_dict)

    data_dir = Path(args.data_dir)
    provider = ParquetProvider(data_dir)
    pairs = [TradingPair(p) for p in args.pairs] if args.pairs else config.data.primary_pairs

    data = {}
    exec_tf = config.data.execution_timeframes[0] if config.data.execution_timeframes else None
    if exec_tf is None:
        logger.error("No execution timeframe configured")
        sys.exit(1)

    for pair in pairs:
        try:
            series = provider.load(pair, exec_tf)
            data[pair] = series
            logger.info("Loaded %s %s: %d bars", pair.value, exec_tf.value, len(series.timestamps))
        except Exception as e:
            logger.warning("Could not load %s: %s", pair.value, e)

    if not data:
        logger.error("No data loaded")
        sys.exit(1)

    runner = PaperTradingRunner(config, output_dir=args.output_dir)
    logger.info("Starting paper trading run: %s", runner.run_id)

    final_state = runner.run(data)

    logger.info("Paper trading complete")
    logger.info("  Run ID: %s", final_state.run_id)
    logger.info("  Bars processed: %d", final_state.bars_processed)
    logger.info("  Final equity: %.2f", final_state.equity)
    logger.info("  Operational state: %s", final_state.operational_state)
    logger.info("  Artifacts: %s/%s/", args.output_dir, runner.run_id)


if __name__ == "__main__":
    main()
