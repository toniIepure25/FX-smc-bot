"""Validate, align, convert to Parquet, resample, and certify acquired data.

Scans all available raw partitions, aligns bid/ask, writes canonical Parquet,
resamples to M5/M15/H1/H4, and produces a comprehensive quality report.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("validate_and_certify")


def _discover_partitions(raw_dir: Path) -> list[dict]:
    """Find all downloaded pair/year/month partitions."""
    partitions = []
    if not raw_dir.exists():
        return partitions
    for pair_dir in sorted(raw_dir.iterdir()):
        if not pair_dir.is_dir():
            continue
        pair = pair_dir.name
        for side_dir in sorted(pair_dir.iterdir()):
            if not side_dir.is_dir() or not side_dir.name.startswith("price="):
                continue
            side = side_dir.name.split("=")[1]
            for year_dir in sorted(side_dir.iterdir()):
                if not year_dir.is_dir() or not year_dir.name.startswith("year="):
                    continue
                year = int(year_dir.name.split("=")[1])
                for month_dir in sorted(year_dir.iterdir()):
                    if not month_dir.is_dir() or not month_dir.name.startswith("month="):
                        continue
                    month = int(month_dir.name.split("=")[1])
                    data_file = month_dir / "data.json"
                    if data_file.exists() and data_file.stat().st_size > 0:
                        partitions.append({
                            "pair": pair, "side": side,
                            "year": year, "month": month,
                            "path": str(data_file),
                        })
    return partitions


def main() -> None:
    from fx_smc_bot.config import Timeframe, TradingPair
    from fx_smc_bot.data.bidask_resampling import resample_bidask
    from fx_smc_bot.data.dukascopy_node_provider import (
        align_bid_ask_month,
        joined_to_parquet,
        parquet_to_bidask_series,
    )
    from fx_smc_bot.data.market_calendar import compute_session_coverage

    raw_dir = Path("data/real/raw/dukascopy-node")
    canonical_dir = Path("data/canonical/dukascopy")
    results_dir = Path("results/gate_c3r")
    results_dir.mkdir(parents=True, exist_ok=True)

    partitions = _discover_partitions(raw_dir)
    logger.info(f"Discovered {len(partitions)} raw partitions")

    pair_months: dict[str, set[tuple[int, int]]] = {}
    for p in partitions:
        pair_months.setdefault(p["pair"], set()).add((p["year"], p["month"]))

    pair_enum_map = {
        "EURUSD": TradingPair.EURUSD,
        "GBPUSD": TradingPair.GBPUSD,
        "USDJPY": TradingPair.USDJPY,
    }

    quality_summary: dict = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "pairs": {},
    }

    for pair_name, months in sorted(pair_months.items()):
        if pair_name not in pair_enum_map:
            logger.warning(f"Unknown pair {pair_name}, skipping")
            continue

        pair = pair_enum_map[pair_name]
        logger.info(f"=== Validating {pair_name} ({len(months)} months) ===")

        pair_total_bid = 0
        pair_total_ask = 0
        pair_total_joined = 0
        pair_total_bid_only = 0
        pair_total_ask_only = 0
        pair_total_neg_spread = 0
        all_spreads: list[float] = []
        all_joined_timestamps: list[int] = []
        month_reports: list[dict] = []
        all_month_violations: list[str] = []

        for year, month in sorted(months):
            logger.info(f"  Processing {pair_name}/{year}-{month:02d}")
            report = align_bid_ask_month(pair, year, month, raw_dir)

            if "error" in report:
                logger.warning(f"    Error: {report['error']}")
                month_reports.append(report)
                continue

            joined = report.pop("joined_data", [])
            pair_total_bid += report.get("bid_rows", 0)
            pair_total_ask += report.get("ask_rows", 0)
            pair_total_joined += report.get("joined_rows", 0)
            pair_total_bid_only += report.get("bid_only", 0)
            pair_total_ask_only += report.get("ask_only", 0)
            pair_total_neg_spread += report.get("negative_spread_count", 0)

            if joined:
                spreads = [r["ask_close"] - r["bid_close"] for r in joined]
                all_spreads.extend(spreads)
                all_joined_timestamps.extend(
                    r["timestamp"] for r in joined
                )

            pq_path = joined_to_parquet(
                joined, pair, year, month, canonical_dir, "M1",
            )
            if pq_path:
                series = parquet_to_bidask_series(pq_path, pair, Timeframe.M1)
                violations = series.validate_invariants()
                if violations:
                    all_month_violations.extend(
                        f"{year}-{month:02d}: {v}" for v in violations
                    )
                else:
                    logger.info(f"    {year}-{month:02d}: invariants OK, {len(joined)} rows")

                for target_tf in [
                    Timeframe.M5, Timeframe.M15,
                    Timeframe.H1, Timeframe.H4,
                ]:
                    resampled = resample_bidask(series, target_tf)
                    tf_dir = (
                        canonical_dir / pair_name
                        / f"timeframe={target_tf.value}"
                        / f"year={year}" / f"month={month:02d}"
                    )
                    tf_dir.mkdir(parents=True, exist_ok=True)
                    import pandas as pd
                    df = pd.DataFrame({
                        "timestamp": resampled.timestamps,
                        "bid_open": resampled.bid_open,
                        "bid_high": resampled.bid_high,
                        "bid_low": resampled.bid_low,
                        "bid_close": resampled.bid_close,
                        "ask_open": resampled.ask_open,
                        "ask_high": resampled.ask_high,
                        "ask_low": resampled.ask_low,
                        "ask_close": resampled.ask_close,
                    })
                    df.to_parquet(
                        str(tf_dir / "part.parquet"),
                        index=False, engine="pyarrow",
                    )

            month_reports.append(report)

        if all_spreads:
            spread_stats = {
                "median_spread": float(np.median(all_spreads)),
                "spread_p90": float(np.percentile(all_spreads, 90)),
                "spread_p95": float(np.percentile(all_spreads, 95)),
                "spread_p99": float(np.percentile(all_spreads, 99)),
                "max_spread": float(max(all_spreads)),
            }
        else:
            spread_stats = {}

        coverage = {}
        if all_joined_timestamps:
            sorted_ts = sorted(all_joined_timestamps)
            first_dt = datetime.fromtimestamp(
                sorted_ts[0] / 1000, tz=timezone.utc,
            )
            last_dt = datetime.fromtimestamp(
                sorted_ts[-1] / 1000, tz=timezone.utc,
            )
            from datetime import timedelta
            coverage = compute_session_coverage(
                sorted_ts,
                first_dt.strftime("%Y-%m-%d"),
                (last_dt + timedelta(days=1)).strftime("%Y-%m-%d"),
            )

        cert_status = "CERTIFIED_PRIMARY_DEVELOPMENT_DATA"
        if pair_total_neg_spread > 0:
            cert_status = "CERTIFIED_EXPLORATORY_ONLY"
        if pair_total_joined < 20000 and len(months) <= 1:
            cert_status = "CERTIFIED_EXPLORATORY_ONLY"
        if all_month_violations:
            cert_status = "CERTIFIED_EXPLORATORY_ONLY"
        if pair_total_joined == 0:
            cert_status = "REJECTED"

        quality_summary["pairs"][pair_name] = {
            "status": cert_status,
            "months_acquired": len(months),
            "bid_rows": pair_total_bid,
            "ask_rows": pair_total_ask,
            "joined_rows": pair_total_joined,
            "bid_only": pair_total_bid_only,
            "ask_only": pair_total_ask_only,
            "negative_spread_count": pair_total_neg_spread,
            **spread_stats,
            "coverage": coverage,
            "violations": all_month_violations if all_month_violations else [],
        }

        logger.info(f"  {pair_name}: {cert_status}")
        logger.info(f"    Months: {len(months)}")
        logger.info(f"    Joined rows: {pair_total_joined}")
        logger.info(f"    Bid-only: {pair_total_bid_only}")
        logger.info(f"    Ask-only: {pair_total_ask_only}")
        logger.info(f"    Neg spread: {pair_total_neg_spread}")

    (results_dir / "data_quality_summary.json").write_text(
        json.dumps(quality_summary, indent=2),
    )
    logger.info(
        f"Quality summary: {results_dir / 'data_quality_summary.json'}"
    )


if __name__ == "__main__":
    main()
