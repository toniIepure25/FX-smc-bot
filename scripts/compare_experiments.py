#!/usr/bin/env python3
"""Compare two or more experiment runs side-by-side.

Usage:
    python scripts/compare_experiments.py results/run_a results/run_b
    python scripts/compare_experiments.py results/run_a results/run_b --diff-config
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fx_smc_bot.research.comparison import (
    compare_configs,
    compare_runs,
    load_run_snapshot,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare experiment runs")
    parser.add_argument("runs", nargs="+", help="Paths to experiment artifact directories")
    parser.add_argument("--diff-config", action="store_true",
                        help="Show configuration differences between runs")
    args = parser.parse_args()

    snapshots = []
    for run_path in args.runs:
        try:
            snap = load_run_snapshot(Path(run_path))
            snapshots.append(snap)
        except Exception as e:
            print(f"Warning: could not load {run_path}: {e}", file=sys.stderr)

    if len(snapshots) < 2:
        print("Need at least 2 valid run directories to compare.", file=sys.stderr)
        sys.exit(1)

    print(compare_runs(snapshots))
    print()

    if args.diff_config:
        print(compare_configs(snapshots))


if __name__ == "__main__":
    main()
