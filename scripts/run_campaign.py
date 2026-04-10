#!/usr/bin/env python3
"""Experiment campaign CLI: run structured multi-experiment campaigns.

Usage:
    python scripts/run_campaign.py baseline_vs_smc --data-dir data/processed
    python scripts/run_campaign.py ablation --data-dir data/processed --type family
    python scripts/run_campaign.py walk_forward --data-dir data/processed --splits 5
    python scripts/run_campaign.py sweep --data-dir data/processed --param risk.base_risk_per_trade --values 0.003 0.005 0.008 0.01
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Experiment campaign runner")
    parser.add_argument("campaign", choices=["baseline_vs_smc", "ablation", "walk_forward", "sweep"],
                        help="Campaign type to run")
    parser.add_argument("--data-dir", type=str, required=True)
    parser.add_argument("--output-dir", type=str, default="campaign_results")
    parser.add_argument("--config", type=str, default=None)
    parser.add_argument("--type", type=str, default="family", help="Ablation type: family, scoring, filter")
    parser.add_argument("--splits", type=int, default=5, help="Walk-forward splits")
    parser.add_argument("--param", type=str, default=None, help="Parameter to sweep (dotted path)")
    parser.add_argument("--values", nargs="+", default=None, help="Values for sweep")
    args = parser.parse_args()

    from fx_smc_bot.config import AppConfig, TradingPair
    from fx_smc_bot.data.providers.parquet_provider import ParquetProvider
    from fx_smc_bot.research.campaigns import (
        run_baseline_vs_smc,
        run_config_sweep,
        run_walk_forward_campaign,
    )
    from fx_smc_bot.research.ablation import (
        run_family_ablation,
        run_filter_ablation,
        run_scoring_ablation,
    )

    config_dict: dict = {}
    if args.config:
        with open(args.config) as f:
            config_dict = yaml.safe_load(f) or {}
    config = AppConfig(**config_dict)

    data_dir = Path(args.data_dir)
    provider = ParquetProvider(data_dir)
    exec_tf = config.data.execution_timeframes[0]

    data = {}
    for pair in config.data.primary_pairs:
        try:
            series = provider.load(pair, exec_tf)
            data[pair] = series
            logger.info("Loaded %s: %d bars", pair.value, len(series.timestamps))
        except Exception as e:
            logger.warning("Could not load %s: %s", pair.value, e)

    if not data:
        logger.error("No data loaded")
        sys.exit(1)

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)

    if args.campaign == "baseline_vs_smc":
        report = run_baseline_vs_smc(config, data)
        print(report.summary_table())
        report.save(output / "baseline_vs_smc.json")

    elif args.campaign == "ablation":
        if args.type == "family":
            result = run_family_ablation(config, data)
        elif args.type == "scoring":
            result = run_scoring_ablation(config, data)
        elif args.type == "filter":
            result = run_filter_ablation(config, data)
        else:
            logger.error("Unknown ablation type: %s", args.type)
            sys.exit(1)
        print(result.summary_table())

    elif args.campaign == "walk_forward":
        report = run_walk_forward_campaign(config, data, n_splits=args.splits)
        print(report.summary_table())
        report.save(output / "walk_forward.json")

    elif args.campaign == "sweep":
        if not args.param or not args.values:
            logger.error("--param and --values required for sweep")
            sys.exit(1)
        overrides = []
        for v in args.values:
            try:
                val = float(v)
            except ValueError:
                val = v
            overrides.append({args.param: val})
        report = run_config_sweep(config, data, overrides)
        print(report.summary_table())
        report.save(output / "sweep.json")

    logger.info("Campaign complete. Artifacts saved to %s", output)


if __name__ == "__main__":
    main()
