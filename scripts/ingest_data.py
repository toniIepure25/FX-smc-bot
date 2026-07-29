"""Ingest and prepare M1/M5/M15 FX data for the validation campaign.

Supports:
  - Dukascopy CSV exports (manual download from JForex or web platform)
  - MetaTrader 5 CSV exports
  - Generic OHLCV CSV files
  - Existing Parquet files (passthrough with validation)

Creates the canonical directory structure under data/real/:
  data/real/
    EURUSD/
      1m.parquet
      5m.parquet   (resampled from 1m)
      15m.parquet  (resampled from 1m)
      1h.parquet   (resampled from 1m)
    GBPUSD/
      ...
    provenance/
      EURUSD_1m.json
      ...

Usage:
    python scripts/ingest_data.py --input data/raw/EURUSD_M1.csv --pair EURUSD --timeframe 1m
    python scripts/ingest_data.py --input data/raw/ --auto-detect
    python scripts/ingest_data.py --generate-synthetic --pairs EURUSD GBPUSD USDJPY
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fx_smc_bot.config import TIMEFRAME_MINUTES, Timeframe, TradingPair
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.data.normalize import CsvFormat, detect_format, normalize_csv, save_parquet
from fx_smc_bot.data.provenance import build_provenance
from fx_smc_bot.data.resampling import resample

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_PAIR_LOOKUP = {p.value.upper(): p for p in TradingPair}
_TF_LOOKUP = {t.value: t for t in Timeframe}

RESAMPLE_TARGETS = [Timeframe.M5, Timeframe.M15, Timeframe.H1, Timeframe.H4]


def _pair_from_string(s: str) -> TradingPair:
    s = s.upper().replace("/", "").replace("_", "")
    if s in _PAIR_LOOKUP:
        return _PAIR_LOOKUP[s]
    raise ValueError(f"Unknown pair: {s}")


def _tf_from_string(s: str) -> Timeframe:
    s = s.lower().replace(" ", "")
    if s in _TF_LOOKUP:
        return _TF_LOOKUP[s]
    raise ValueError(f"Unknown timeframe: {s}")


def _df_to_barseries(df: pd.DataFrame, pair: TradingPair, tf: Timeframe) -> BarSeries:
    timestamps = df["timestamp"].values.astype("datetime64[ns]")
    return BarSeries(
        pair=pair,
        timeframe=tf,
        timestamps=timestamps,
        open=df["open"].values.astype(np.float64),
        high=df["high"].values.astype(np.float64),
        low=df["low"].values.astype(np.float64),
        close=df["close"].values.astype(np.float64),
        volume=df["volume"].values.astype(np.float64) if "volume" in df.columns else None,
        spread=df["spread"].values.astype(np.float64) if "spread" in df.columns else None,
    )


def ingest_single_file(
    input_path: Path,
    pair: TradingPair,
    timeframe: Timeframe,
    output_dir: Path,
    source_name: str = "unknown",
    price_type: str = "unknown",
    spread_source: str = "none",
) -> dict:
    """Ingest a single CSV/Parquet file and produce canonical output."""
    pair_dir = output_dir / pair.value
    pair_dir.mkdir(parents=True, exist_ok=True)
    prov_dir = output_dir / "provenance"
    prov_dir.mkdir(parents=True, exist_ok=True)

    if input_path.suffix == ".parquet":
        df = pd.read_parquet(input_path)
        if "timestamp" in df.columns and df["timestamp"].dt.tz is None:
            df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")
    else:
        df = normalize_csv(input_path)

    logger.info("Loaded %d rows from %s", len(df), input_path)

    base_series = _df_to_barseries(df, pair, timeframe)

    out_path = save_parquet(df, pair_dir / f"{timeframe.value}.parquet")
    logger.info("Saved base %s %s: %d bars -> %s", pair.value, timeframe.value, len(df), out_path)

    prov = build_provenance(
        base_series,
        source=source_name,
        price_type=price_type,
        spread_source=spread_source,
        download_date=date.today(),
        file_path=input_path,
    )
    prov_path = prov_dir / f"{pair.value}_{timeframe.value}.json"
    prov.save(prov_path)
    logger.info("Provenance saved to %s", prov_path)

    base_minutes = TIMEFRAME_MINUTES[timeframe]
    resampled = {}
    for target_tf in RESAMPLE_TARGETS:
        target_minutes = TIMEFRAME_MINUTES[target_tf]
        if target_minutes <= base_minutes:
            continue
        try:
            rs = resample(base_series, target_tf)
            rs_df = pd.DataFrame({
                "timestamp": rs.timestamps,
                "open": rs.open,
                "high": rs.high,
                "low": rs.low,
                "close": rs.close,
            })
            if rs.volume is not None:
                rs_df["volume"] = rs.volume
            rs_out = save_parquet(rs_df, pair_dir / f"{target_tf.value}.parquet")
            resampled[target_tf.value] = len(rs)
            logger.info("Resampled %s -> %s: %d bars -> %s", timeframe.value, target_tf.value, len(rs), rs_out)
        except Exception as e:
            logger.warning("Failed to resample %s to %s: %s", pair.value, target_tf.value, e)

    return {
        "pair": pair.value,
        "base_timeframe": timeframe.value,
        "base_bars": len(df),
        "resampled": resampled,
        "provenance": str(prov_path),
        "missing_intervals": len(prov.missing_intervals) if prov.missing_intervals else 0,
        "duplicate_count": prov.duplicate_count,
    }


def generate_synthetic(
    pairs: list[TradingPair],
    output_dir: Path,
    start_date: str = "2016-01-04",
    end_date: str = "2024-12-31",
    seed: int = 42,
) -> list[dict]:
    from fx_smc_bot.data.providers.dukascopy import generate_realistic_data

    results = []
    for pair in pairs:
        logger.info("Generating synthetic M5 data for %s (%s to %s)", pair.value, start_date, end_date)
        df = generate_realistic_data(pair, Timeframe.M5, start_date, end_date, seed=seed)
        pair_dir = output_dir / pair.value
        pair_dir.mkdir(parents=True, exist_ok=True)

        out = save_parquet(df, pair_dir / "5m.parquet")
        series = _df_to_barseries(df, pair, Timeframe.M5)

        prov_dir = output_dir / "provenance"
        prov_dir.mkdir(parents=True, exist_ok=True)
        prov = build_provenance(
            series, source="synthetic_dukascopy_generator",
            price_type="mid", spread_source="synthetic",
            download_date=date.today(),
        )
        prov.save(prov_dir / f"{pair.value}_5m.json")

        resampled = {}
        for target_tf in [Timeframe.M15, Timeframe.H1, Timeframe.H4]:
            try:
                rs = resample(series, target_tf)
                rs_df = pd.DataFrame({
                    "timestamp": rs.timestamps, "open": rs.open,
                    "high": rs.high, "low": rs.low, "close": rs.close,
                })
                if rs.volume is not None:
                    rs_df["volume"] = rs.volume
                save_parquet(rs_df, pair_dir / f"{target_tf.value}.parquet")
                resampled[target_tf.value] = len(rs)
            except Exception as e:
                logger.warning("Failed to resample %s: %s", target_tf.value, e)

        results.append({
            "pair": pair.value, "base_bars": len(df),
            "resampled": resampled, "source": "synthetic",
        })

    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest FX data for validation campaign")
    parser.add_argument("--input", type=Path, help="Input CSV/Parquet file or directory")
    parser.add_argument("--pair", type=str, help="Trading pair (e.g., EURUSD)")
    parser.add_argument("--timeframe", type=str, default="1m", help="Source timeframe")
    parser.add_argument("--source", type=str, default="unknown", help="Data source name")
    parser.add_argument("--price-type", choices=["bid_ask", "mid", "unknown"], default="unknown")
    parser.add_argument("--spread-source", choices=["historical", "synthetic", "none"], default="none")
    parser.add_argument("--output-dir", type=Path, default=Path("data/real"), help="Output directory")
    parser.add_argument("--generate-synthetic", action="store_true", help="Generate synthetic data instead")
    parser.add_argument("--pairs", nargs="+", default=["EURUSD", "GBPUSD", "USDJPY"])
    parser.add_argument("--start-date", default="2016-01-04")
    parser.add_argument("--end-date", default="2024-12-31")
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.generate_synthetic:
        pairs = [_pair_from_string(p) for p in args.pairs]
        results = generate_synthetic(
            pairs, args.output_dir,
            start_date=args.start_date,
            end_date=args.end_date,
            seed=args.seed,
        )
        for r in results:
            logger.info("Synthetic: %s — %d bars, resampled: %s", r["pair"], r["base_bars"], r["resampled"])
        return 0

    if args.input is None:
        logger.error("--input is required (or use --generate-synthetic)")
        return 1

    if args.input.is_dir():
        all_results = []
        for f in sorted(args.input.glob("*.csv")) + sorted(args.input.glob("*.parquet")):
            pair_hint = None
            for p in TradingPair:
                if p.value.upper() in f.stem.upper():
                    pair_hint = p
                    break
            if pair_hint is None and args.pair:
                pair_hint = _pair_from_string(args.pair)
            if pair_hint is None:
                logger.warning("Cannot determine pair for %s, skipping", f.name)
                continue
            tf = _tf_from_string(args.timeframe)
            result = ingest_single_file(
                f, pair_hint, tf, args.output_dir,
                source_name=args.source, price_type=args.price_type,
                spread_source=args.spread_source,
            )
            all_results.append(result)
        for r in all_results:
            logger.info("Ingested: %s %s — %d bars", r["pair"], r["base_timeframe"], r["base_bars"])
    else:
        pair = _pair_from_string(args.pair)
        tf = _tf_from_string(args.timeframe)
        result = ingest_single_file(
            args.input, pair, tf, args.output_dir,
            source_name=args.source, price_type=args.price_type,
            spread_source=args.spread_source,
        )
        logger.info("Ingested: %s %s — %d bars, missing: %d, dups: %d",
                     result["pair"], result["base_timeframe"], result["base_bars"],
                     result["missing_intervals"], result["duplicate_count"])

    return 0


if __name__ == "__main__":
    sys.exit(main())
