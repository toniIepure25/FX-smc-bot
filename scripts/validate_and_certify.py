"""Validate, align, convert to Parquet, resample, and certify acquired data."""
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


def main() -> None:
    from fx_smc_bot.config import Timeframe, TradingPair
    from fx_smc_bot.data.bidask_resampling import resample_bidask
    from fx_smc_bot.data.dukascopy_node_provider import (
        align_bid_ask_month,
        joined_to_parquet,
        parquet_to_bidask_series,
    )

    raw_dir = Path("data/real/raw/dukascopy-node")
    canonical_dir = Path("data/canonical/dukascopy")
    results_dir = Path("results/gate_c3r")
    results_dir.mkdir(parents=True, exist_ok=True)

    pairs = [TradingPair.EURUSD, TradingPair.GBPUSD, TradingPair.USDJPY]
    quality_summary: dict = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "pairs": {},
    }

    for pair in pairs:
        logger.info(f"=== Validating {pair.value} ===")

        report = align_bid_ask_month(pair, 2023, 6, raw_dir)

        if "error" in report:
            logger.error(f"  Alignment error: {report['error']}")
            quality_summary["pairs"][pair.value] = {
                "status": "REJECTED",
                "error": report["error"],
            }
            continue

        joined = report.pop("joined_data", [])
        logger.info(f"  Bid rows: {report['bid_rows']}")
        logger.info(f"  Ask rows: {report['ask_rows']}")
        logger.info(f"  Joined rows: {report['joined_rows']}")
        logger.info(f"  Bid-only rows: {report['bid_only']}")
        logger.info(f"  Ask-only rows: {report['ask_only']}")
        logger.info(
            f"  Negative spread: {report['negative_spread_count']}"
        )
        if "median_spread" in report:
            logger.info(f"  Median spread: {report['median_spread']:.6f}")
            logger.info(f"  P90 spread: {report['spread_p90']:.6f}")
            logger.info(f"  P95 spread: {report['spread_p95']:.6f}")
            logger.info(f"  P99 spread: {report['spread_p99']:.6f}")
            logger.info(f"  Max spread: {report['max_spread']:.6f}")

        pq_path = joined_to_parquet(
            joined, pair, 2023, 6, canonical_dir, "M1",
        )
        logger.info(f"  Parquet written: {pq_path}")

        if pq_path:
            series = parquet_to_bidask_series(
                pq_path, pair, Timeframe.M1,
            )
            violations = series.validate_invariants()
            if violations:
                for v in violations:
                    logger.warning(f"  Invariant violation: {v}")
            else:
                logger.info("  All bid/ask invariants pass")

            timestamps = series.timestamps
            diffs = np.diff(
                timestamps.astype("int64"),
            ) / 1_000_000_000 / 60
            logger.info(f"  Timestamp range: {timestamps[0]} to {timestamps[-1]}")
            logger.info(f"  Min gap (min): {diffs.min():.1f}")
            logger.info(f"  Max gap (min): {diffs.max():.1f}")
            logger.info(f"  Median gap (min): {np.median(diffs):.1f}")

            for target_tf in [
                Timeframe.M5, Timeframe.M15,
                Timeframe.H1, Timeframe.H4,
            ]:
                resampled = resample_bidask(series, target_tf)
                tf_dir = (
                    canonical_dir / pair.value
                    / f"timeframe={target_tf.value}"
                    / "year=2023" / "month=06"
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
                logger.info(
                    f"  Resampled {target_tf.value}: "
                    f"{len(resampled)} bars"
                )

            cert_status = "CERTIFIED_PRIMARY_DEVELOPMENT_DATA"
            if report["negative_spread_count"] > 0:
                cert_status = "CERTIFIED_EXPLORATORY_ONLY"
            if report["joined_rows"] < 20000:
                cert_status = "CERTIFIED_EXPLORATORY_ONLY"

        else:
            cert_status = "REJECTED"

        quality_summary["pairs"][pair.value] = {
            "status": cert_status,
            **report,
        }

    (results_dir / "data_quality_summary.json").write_text(
        json.dumps(quality_summary, indent=2),
    )
    logger.info(
        f"Quality summary written to {results_dir / 'data_quality_summary.json'}"
    )

    for p, info in quality_summary["pairs"].items():
        logger.info(f"  {p}: {info['status']}")


if __name__ == "__main__":
    main()
