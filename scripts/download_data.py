#!/usr/bin/env python3
"""Download / generate FX data and store as normalized Parquet files.

Usage:
    # Generate realistic synthetic data for all pairs and timeframes
    python scripts/download_data.py --mode generate --output-dir data/processed

    # Import Dukascopy CSV exports
    python scripts/download_data.py --mode import --input-dir data/raw --output-dir data/processed

    # Inspect existing dataset
    python scripts/download_data.py --mode inspect --output-dir data/processed
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fx_smc_bot.config import TIMEFRAME_MINUTES, Timeframe, TradingPair
from fx_smc_bot.data.diagnostics import format_diagnostic_report, run_diagnostics
from fx_smc_bot.data.manifest import DataManifest, DatasetEntry
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.data.normalize import load_parquet, normalize_csv, save_parquet
from fx_smc_bot.data.providers.dukascopy import generate_realistic_data
from fx_smc_bot.data.providers.parquet_provider import ParquetProvider
from fx_smc_bot.data.resampling import resample
from fx_smc_bot.data.validation import validate
from fx_smc_bot.utils.logging import setup_logging


def _generate(output_dir: Path, start: str, end: str, seed: int) -> None:
    """Generate realistic synthetic data for all pairs and timeframes."""
    logger = logging.getLogger(__name__)
    manifest = DataManifest(name="synthetic_fx", description=f"Synthetic {start} to {end}")
    pairs = [TradingPair.EURUSD, TradingPair.GBPUSD, TradingPair.USDJPY]
    base_tf = Timeframe.M1

    for pair in pairs:
        logger.info("Generating M1 data for %s...", pair.value)
        df = generate_realistic_data(pair, base_tf, start, end, seed=seed)
        pair_dir = output_dir / pair.value
        pair_dir.mkdir(parents=True, exist_ok=True)

        m1_path = save_parquet(df, pair_dir / f"{base_tf.value}.parquet")
        manifest.add_entry(DatasetEntry(
            pair=pair.value, timeframe=base_tf.value, source="synthetic",
            file_path=str(m1_path), bar_count=len(df),
            start_date=str(df["timestamp"].iloc[0])[:10],
            end_date=str(df["timestamp"].iloc[-1])[:10],
        ))

        # Derive higher timeframes
        m1_series = _df_to_barseries(df, pair, base_tf)
        for tf in [Timeframe.M5, Timeframe.M15, Timeframe.H1, Timeframe.H4, Timeframe.D1]:
            logger.info("  Resampling %s -> %s", base_tf.value, tf.value)
            resampled = resample(m1_series, tf)
            rs_df = _barseries_to_df(resampled)
            tf_path = save_parquet(rs_df, pair_dir / f"{tf.value}.parquet")
            manifest.add_entry(DatasetEntry(
                pair=pair.value, timeframe=tf.value, source=f"resampled_from_{base_tf.value}",
                file_path=str(tf_path), bar_count=len(rs_df),
                start_date=str(rs_df["timestamp"].iloc[0])[:10],
                end_date=str(rs_df["timestamp"].iloc[-1])[:10],
            ))

    manifest_path = output_dir / "manifest.json"
    manifest.save(manifest_path)
    logger.info("Generation complete.\n%s", manifest.summary())


def _import_csvs(input_dir: Path, output_dir: Path) -> None:
    """Import CSV files from input_dir, normalize, and store as Parquet."""
    logger = logging.getLogger(__name__)
    manifest = DataManifest(name="imported_fx", description=f"Imported from {input_dir}")

    for pair in TradingPair:
        pair_input = input_dir / pair.value
        if not pair_input.is_dir():
            continue
        for csv_file in sorted(pair_input.glob("*.csv")):
            tf_str = csv_file.stem
            try:
                tf = Timeframe(tf_str)
            except ValueError:
                logger.warning("Skipping %s (unknown timeframe)", csv_file)
                continue

            logger.info("Normalizing %s/%s...", pair.value, tf.value)
            df = normalize_csv(csv_file)
            pair_dir = output_dir / pair.value
            pq_path = save_parquet(df, pair_dir / f"{tf.value}.parquet")
            manifest.add_entry(DatasetEntry(
                pair=pair.value, timeframe=tf.value, source=f"csv:{csv_file.name}",
                file_path=str(pq_path), bar_count=len(df),
                start_date=str(df["timestamp"].iloc[0])[:10],
                end_date=str(df["timestamp"].iloc[-1])[:10],
            ))

    manifest.save(output_dir / "manifest.json")
    logger.info("Import complete.\n%s", manifest.summary())


def _inspect(data_dir: Path) -> None:
    """Inspect all datasets in a directory and run diagnostics."""
    provider = ParquetProvider(data_dir)
    for pair in provider.available_pairs():
        for tf in provider.available_timeframes(pair):
            series = provider.load(pair, tf)
            report = run_diagnostics(series)
            print(format_diagnostic_report(report))
            print()


def _df_to_barseries(df, pair, tf):
    import numpy as np
    return BarSeries(
        pair=pair, timeframe=tf,
        timestamps=df["timestamp"].values.astype("datetime64[ns]"),
        open=df["open"].values.astype(np.float64),
        high=df["high"].values.astype(np.float64),
        low=df["low"].values.astype(np.float64),
        close=df["close"].values.astype(np.float64),
        volume=df["volume"].values.astype(np.float64) if "volume" in df.columns else None,
        spread=df["spread"].values.astype(np.float64) if "spread" in df.columns else None,
    )


def _barseries_to_df(series):
    import pandas as pd
    d = {"timestamp": series.timestamps, "open": series.open, "high": series.high,
         "low": series.low, "close": series.close}
    if series.volume is not None:
        d["volume"] = series.volume
    return pd.DataFrame(d)


def main() -> None:
    parser = argparse.ArgumentParser(description="FX data pipeline")
    parser.add_argument("--mode", choices=["generate", "import", "inspect"], default="generate")
    parser.add_argument("--output-dir", type=str, default="data/processed")
    parser.add_argument("--input-dir", type=str, default="data/raw")
    parser.add_argument("--start", type=str, default="2023-01-02")
    parser.add_argument("--end", type=str, default="2024-12-31")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    setup_logging("INFO")
    output = Path(args.output_dir)

    if args.mode == "generate":
        _generate(output, args.start, args.end, args.seed)
    elif args.mode == "import":
        _import_csvs(Path(args.input_dir), output)
    elif args.mode == "inspect":
        _inspect(output)


if __name__ == "__main__":
    main()
