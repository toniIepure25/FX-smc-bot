"""Acquisition observability: status report across all partitions.

Usage:
    python scripts/acquisition_status.py --state-dir data/acquisition_state
    python scripts/acquisition_status.py --raw-dir data/raw/dukascopy-node --scan
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fx_smc_bot.data.daily_checkpoint import (  # noqa: E402
    load_month_manifest,
)
from fx_smc_bot.data.dukascopy_node_provider import (  # noqa: E402
    _month_range,
)
from scripts.run_persistent_acquisition import (  # noqa: E402
    PersistentRunner,
)


def scan_partitions(
    raw_dir: Path,
    pairs: list[str],
    start_year: int,
    start_month: int,
    end_year: int,
    end_month: int,
) -> dict:
    """Scan raw data directory for partition status."""
    total = 0
    complete = 0
    pending = 0
    failed = 0
    total_rows = 0
    total_bytes = 0
    failed_details: list[dict] = []

    for pair in pairs:
        for year, month in _month_range(
            start_year, start_month, end_year, end_month,
        ):
            for side in ("bid", "ask"):
                total += 1
                manifest = load_month_manifest(
                    raw_dir, pair, side, year, month,
                )
                if manifest is None:
                    pending += 1
                    continue
                if manifest.compacted:
                    complete += 1
                    total_rows += manifest.compacted_rows
                    continue

                day_complete = sum(
                    1 for d in manifest.days
                    if d.status in ("complete", "market_closed")
                )
                day_failed = sum(
                    1 for d in manifest.days if d.status == "failed"
                )
                day_total = len(manifest.days)
                if day_failed > 0:
                    failed += 1
                    failed_details.append({
                        "partition": f"{pair}/{side}/{year}-{month:02d}",
                        "days_complete": day_complete,
                        "days_failed": day_failed,
                        "days_total": day_total,
                    })
                else:
                    pending += 1

    return {
        "total_partitions": total,
        "complete": complete,
        "pending": pending,
        "failed": failed,
        "total_rows": total_rows,
        "total_bytes": total_bytes,
        "failed_details": failed_details[:20],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Acquisition status report",
    )
    parser.add_argument("--state-dir", default="data/acquisition_state")
    parser.add_argument("--raw-dir", default="data/raw/dukascopy-node")
    parser.add_argument("--scan", action="store_true")
    parser.add_argument("--pairs", nargs="+", default=["EURUSD", "GBPUSD", "USDJPY"])
    parser.add_argument("--start", default="2019-01-01")
    parser.add_argument("--end", default="2019-12-31")

    args = parser.parse_args()

    status = PersistentRunner.get_status(Path(args.state_dir))
    print("=== Runner Status ===")
    print(json.dumps(status, indent=2))

    if args.scan:
        start_parts = args.start.split("-")
        end_parts = args.end.split("-")
        scan = scan_partitions(
            Path(args.raw_dir),
            args.pairs,
            int(start_parts[0]), int(start_parts[1]),
            int(end_parts[0]), int(end_parts[1]),
        )
        print("\n=== Partition Scan ===")
        print(json.dumps(scan, indent=2))


if __name__ == "__main__":
    main()
