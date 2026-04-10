#!/usr/bin/env python3
"""Inspect market data: validate, show statistics, session distribution.

Usage:
    python scripts/inspect_data.py --data-dir data/raw --pair EURUSD --timeframe 15m
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fx_smc_bot.config import SessionConfig, Timeframe, TradingPair
from fx_smc_bot.data.providers.csv_provider import CsvProvider
from fx_smc_bot.data.sessions import label_sessions
from fx_smc_bot.data.validation import validate


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect FX market data")
    parser.add_argument("--data-dir", type=str, required=True)
    parser.add_argument("--pair", type=str, required=True)
    parser.add_argument("--timeframe", type=str, required=True)
    args = parser.parse_args()

    pair = TradingPair(args.pair)
    tf = Timeframe(args.timeframe)
    provider = CsvProvider(args.data_dir)

    print(f"Loading {pair.value} / {tf.value}...")
    series = provider.load(pair, tf)
    print(f"  Bars: {len(series)}")
    print(f"  Date range: {series.timestamps[0]} -> {series.timestamps[-1]}")

    report = validate(series)
    print(f"\nValidation:")
    print(f"  Total bars:          {report.total_bars}")
    print(f"  Duplicate timestamps: {report.duplicate_timestamps}")
    print(f"  Zero-range bars:     {report.zero_range_bars}")
    print(f"  Negative-range bars: {report.negative_range_bars}")
    print(f"  Timestamp gaps:      {report.timestamp_gaps}")
    print(f"  H/L violations:      {report.high_low_violations}")
    print(f"  Clean: {report.is_clean}")

    labels = label_sessions(series.timestamps, SessionConfig())
    from collections import Counter
    dist = Counter(str(l) if l else "none" for l in labels)
    print(f"\nSession distribution:")
    for session, count in sorted(dist.items()):
        print(f"  {session:24s}: {count}")


if __name__ == "__main__":
    main()
