"""Dukascopy-node M1 bid/ask acquisition CLI.

Usage:
    python scripts/acquire_dukascopy_node_history.py \
        --pairs EURUSD GBPUSD USDJPY \
        --start 2015-01-01 --end 2025-12-31 \
        --output-dir data/real --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("acquire_dukascopy_node")

PAIR_MAP = {"EURUSD": "EURUSD", "GBPUSD": "GBPUSD", "USDJPY": "USDJPY"}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Acquire M1 bid/ask FX data via dukascopy-node",
    )
    parser.add_argument("--pairs", nargs="+", required=True)
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--output-dir", default="data/real")
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    from fx_smc_bot.config import TradingPair
    from fx_smc_bot.data.dukascopy_node_provider import (
        AcquisitionManifest,
        acquire_pair,
        plan_acquisition,
    )

    pairs = []
    for p in args.pairs:
        if p not in PAIR_MAP:
            logger.error(f"Unsupported pair: {p}")
            sys.exit(1)
        pairs.append(TradingPair(p))

    raw_dir = Path(args.output_dir) / "raw" / "dukascopy-node"
    raw_dir.mkdir(parents=True, exist_ok=True)

    plan = plan_acquisition(pairs, args.start, args.end, raw_dir)
    logger.info("Acquisition plan:")
    for k, v in plan.items():
        logger.info(f"  {k}: {v}")

    if args.dry_run:
        plan_file = Path(args.output_dir) / "acquisition_plan.json"
        plan_file.parent.mkdir(parents=True, exist_ok=True)
        plan_file.write_text(json.dumps(plan, indent=2))
        logger.info(f"Plan written to {plan_file}")
        return

    start_dt = datetime.strptime(args.start, "%Y-%m-%d")
    end_dt = datetime.strptime(args.end, "%Y-%m-%d")

    manifest = AcquisitionManifest(
        pairs=[p.value for p in pairs],
        start=args.start,
        end=args.end,
        timeframe="m1",
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    for pair in pairs:
        logger.info(f"=== Acquiring {pair.value} ===")
        results = acquire_pair(
            pair,
            start_dt.year, start_dt.month,
            end_dt.year, end_dt.month,
            raw_dir,
            timeframe="m1",
            batch_size=args.batch_size,
            retries=args.retries,
        )
        manifest.partitions.extend(results)

    manifest_dir = Path(args.output_dir) / "manifests" / "dukascopy-node"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = manifest_dir / "acquisition_manifest.json"
    manifest_file.write_text(json.dumps(manifest.to_dict(), indent=2))

    complete = sum(1 for p in manifest.partitions if p.status == "complete")
    failed = sum(1 for p in manifest.partitions if p.status == "failed")
    total_rows = sum(p.rows for p in manifest.partitions)

    logger.info("Acquisition complete:")
    logger.info(f"  Partitions: {len(manifest.partitions)}")
    logger.info(f"  Complete: {complete}")
    logger.info(f"  Failed: {failed}")
    logger.info(f"  Total rows: {total_rows}")


if __name__ == "__main__":
    main()
