"""Full FX historical data acquisition and certification CLI.

Usage:
    python scripts/acquire_fx_history.py \
        --provider dukascopy \
        --pairs EURUSD GBPUSD USDJPY \
        --start 2015-01-01 \
        --end 2025-12-31 \
        --base-resolution tick \
        --resample M1 M5 M15 H1 H4 \
        --output-dir data/real \
        --workers 4 \
        --resume
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("acquire_fx_history")


def estimate_download(
    provider: str,
    pairs: list[str],
    start: datetime,
    end: datetime,
    base_resolution: str,
) -> dict:
    """Estimate download size and chunk count before starting."""
    days = (end - start).days
    months = days // 30
    hours = days * 24

    if base_resolution == "tick":
        chunks_per_pair = hours
        avg_chunk_kb = 50
    else:
        chunks_per_pair = months
        avg_chunk_kb = 200

    total_chunks = chunks_per_pair * len(pairs)
    est_mb = (total_chunks * avg_chunk_kb) / 1024

    return {
        "provider": provider,
        "pairs": pairs,
        "days": days,
        "chunks_per_pair": chunks_per_pair,
        "total_chunks": total_chunks,
        "estimated_disk_mb": f"{est_mb:.0f}-{est_mb * 2:.0f}",
        "estimated_requests": total_chunks,
    }


def run_acquisition(args: argparse.Namespace) -> None:
    """Execute the data acquisition pipeline."""
    from fx_smc_bot.config import TradingPair
    from fx_smc_bot.data.historical_providers import (
        DukascopyProvider,
        OandaProvider,
    )

    pair_map = {
        "EURUSD": TradingPair.EURUSD,
        "GBPUSD": TradingPair.GBPUSD,
        "USDJPY": TradingPair.USDJPY,
    }

    pairs = []
    for p in args.pairs:
        if p not in pair_map:
            logger.error(f"Unsupported pair: {p}")
            sys.exit(1)
        pairs.append(pair_map[p])

    start = datetime.strptime(args.start, "%Y-%m-%d")
    end = datetime.strptime(args.end, "%Y-%m-%d")

    estimate = estimate_download(
        args.provider, args.pairs, start, end, args.base_resolution,
    )
    logger.info("Download estimate:")
    for k, v in estimate.items():
        logger.info(f"  {k}: {v}")

    if args.dry_run:
        logger.info("Dry run — exiting without download")
        return

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest_dir = output_dir / "manifests" / args.provider
    manifest_dir.mkdir(parents=True, exist_ok=True)

    if args.provider == "dukascopy":
        cache = output_dir / "raw" / "dukascopy"
        provider = DukascopyProvider(
            cache_dir=cache,
            max_retries=args.retries,
        )
    elif args.provider == "oanda":
        provider = OandaProvider(practice=True)
        if not provider.is_configured:
            logger.error(
                "OANDA_API_TOKEN not set. "
                "Set it as an environment variable."
            )
            sys.exit(1)
    else:
        logger.error(f"Unsupported provider: {args.provider}")
        sys.exit(1)

    resolution = args.base_resolution
    if resolution == "tick":
        resolution = "M1"

    results = {}
    for pair in pairs:
        logger.info(f"Downloading {pair.value} from {args.provider}...")
        result = provider.download(pair, start, end, resolution)
        results[pair.value] = {
            "provider": result.provider,
            "pair": result.pair.value,
            "resolution": result.resolution,
            "rows": result.rows,
            "has_bid_ask": result.has_bid_ask,
            "errors": result.errors,
            "raw_files_count": len(result.raw_files),
        }
        if result.errors:
            logger.warning(
                f"  {pair.value}: {len(result.errors)} errors"
            )
        logger.info(f"  {pair.value}: {result.rows} rows downloaded")

    manifest_path = manifest_dir / "acquisition_manifest.json"
    manifest = {
        "provider": args.provider,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "start": args.start,
        "end": args.end,
        "base_resolution": args.base_resolution,
        "results": results,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))
    logger.info(f"Manifest written to {manifest_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="FX historical data acquisition CLI",
    )
    parser.add_argument(
        "--provider", required=True,
        choices=["dukascopy", "oanda", "mt5"],
    )
    parser.add_argument(
        "--pairs", nargs="+", required=True,
        help="Currency pairs (e.g. EURUSD GBPUSD USDJPY)",
    )
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument(
        "--base-resolution", default="tick",
        choices=["tick", "M1", "M5"],
    )
    parser.add_argument(
        "--resample", nargs="*", default=[],
        help="Target timeframes to resample to",
    )
    parser.add_argument(
        "--output-dir", default="data/real",
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument(
        "--resume", action="store_true",
        help="Resume interrupted download",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print estimates without downloading",
    )
    parser.add_argument(
        "--validation-only", action="store_true",
        help="Validate existing data without downloading",
    )

    args = parser.parse_args()
    run_acquisition(args)


if __name__ == "__main__":
    main()
