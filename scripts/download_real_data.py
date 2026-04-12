#!/usr/bin/env python3
"""Download real historical FX data from Yahoo Finance.

Downloads H1 (2 years), H4 (2 years), and M15 (60 days) OHLCV data
for EURUSD, GBPUSD, USDJPY. Saves as CSV in data/real/{PAIR}/{tf}.csv
and runs data quality diagnostics on every file.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fx_smc_bot.config import Timeframe, TradingPair
from fx_smc_bot.data.diagnostics import DiagnosticReport, format_diagnostic_report, run_diagnostics
from fx_smc_bot.data.models import BarSeries

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-25s | %(levelname)-5s | %(message)s",
)
logger = logging.getLogger("download_real_data")

PAIRS = {
    TradingPair.EURUSD: "EURUSD=X",
    TradingPair.GBPUSD: "GBPUSD=X",
    TradingPair.USDJPY: "USDJPY=X",
}

DOWNLOADS = [
    (Timeframe.H1, "2y", "1h"),
    (Timeframe.H4, "2y", None),   # H4 not directly available; resample from H1
    (Timeframe.M15, "60d", "15m"),
]


def _download_yf(ticker: str, period: str, interval: str) -> pd.DataFrame:
    """Download OHLCV from Yahoo Finance and normalize columns."""
    t = yf.Ticker(ticker)
    df = t.history(period=period, interval=interval)
    if df.empty:
        return df

    df = df.reset_index()
    ts_col = [c for c in df.columns if "date" in c.lower() or "datetime" in c.lower()][0]
    df = df.rename(columns={
        ts_col: "timestamp",
        "Open": "open", "High": "high", "Low": "low", "Close": "close",
        "Volume": "volume",
    })
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["timestamp"] = df["timestamp"].dt.tz_localize(None)

    keep = ["timestamp", "open", "high", "low", "close", "volume"]
    return df[[c for c in keep if c in df.columns]].sort_values("timestamp").reset_index(drop=True)


def _resample_h1_to_h4(df_h1: pd.DataFrame) -> pd.DataFrame:
    """Resample H1 dataframe to H4 using standard OHLCV aggregation."""
    df = df_h1.set_index("timestamp")
    ohlcv = df.resample("4h").agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
        "volume": "sum",
    }).dropna(subset=["open"])
    return ohlcv.reset_index()


def _df_to_barseries(df: pd.DataFrame, pair: TradingPair, tf: Timeframe) -> BarSeries:
    return BarSeries(
        pair=pair, timeframe=tf,
        timestamps=df["timestamp"].values.astype("datetime64[ns]"),
        open=df["open"].values.astype(np.float64),
        high=df["high"].values.astype(np.float64),
        low=df["low"].values.astype(np.float64),
        close=df["close"].values.astype(np.float64),
        volume=df["volume"].values.astype(np.float64) if "volume" in df.columns else None,
    )


def main() -> None:
    output_dir = Path(__file__).resolve().parent.parent / "data" / "real"
    output_dir.mkdir(parents=True, exist_ok=True)

    all_reports: list[tuple[str, str, DiagnosticReport]] = []
    h1_cache: dict[TradingPair, pd.DataFrame] = {}

    for pair, ticker in PAIRS.items():
        pair_dir = output_dir / pair.value
        pair_dir.mkdir(parents=True, exist_ok=True)

        # --- H1 ---
        logger.info("Downloading %s H1 (2 years)...", pair.value)
        df_h1 = _download_yf(ticker, "2y", "1h")
        if df_h1.empty:
            logger.error("No H1 data for %s", pair.value)
            continue
        h1_path = pair_dir / "1h.csv"
        df_h1.to_csv(h1_path, index=False)
        h1_cache[pair] = df_h1
        series = _df_to_barseries(df_h1, pair, Timeframe.H1)
        report = run_diagnostics(series)
        all_reports.append((pair.value, "1h", report))
        logger.info("  %s H1: %d bars, quality=%.3f", pair.value, len(df_h1), report.quality_score)

        # --- H4 (resample from H1) ---
        logger.info("Resampling %s H4 from H1...", pair.value)
        df_h4 = _resample_h1_to_h4(df_h1)
        h4_path = pair_dir / "4h.csv"
        df_h4.to_csv(h4_path, index=False)
        series_h4 = _df_to_barseries(df_h4, pair, Timeframe.H4)
        report_h4 = run_diagnostics(series_h4)
        all_reports.append((pair.value, "4h", report_h4))
        logger.info("  %s H4: %d bars, quality=%.3f", pair.value, len(df_h4), report_h4.quality_score)

        # --- M15 ---
        logger.info("Downloading %s M15 (60 days)...", pair.value)
        df_m15 = _download_yf(ticker, "60d", "15m")
        if df_m15.empty:
            logger.warning("No M15 data for %s", pair.value)
        else:
            m15_path = pair_dir / "15m.csv"
            df_m15.to_csv(m15_path, index=False)
            series_m15 = _df_to_barseries(df_m15, pair, Timeframe.M15)
            report_m15 = run_diagnostics(series_m15)
            all_reports.append((pair.value, "15m", report_m15))
            logger.info("  %s M15: %d bars, quality=%.3f", pair.value, len(df_m15), report_m15.quality_score)

    # --- Readiness report ---
    lines = [
        "# Real Data Readiness Report",
        f"\n**Generated**: {datetime.utcnow().isoformat()[:19]}Z",
        f"**Source**: Yahoo Finance (yfinance)",
        f"**Pairs**: {', '.join(p.value for p in PAIRS)}",
        "",
        "## Dataset Inventory",
        "",
        "| Pair | TF | Bars | Date Range | Missing% | Dups | Quality |",
        "|------|----|------|------------|----------|------|---------|",
    ]
    for pair_str, tf_str, r in all_reports:
        lines.append(
            f"| {pair_str} | {tf_str} | {r.total_bars:,d} | {r.date_range} | "
            f"{r.missing_bar_pct:.1%} | {r.duplicate_count} | {r.quality_score:.3f} |"
        )

    lines.append("")
    lines.append("## Per-Dataset Diagnostics")
    lines.append("")
    for pair_str, tf_str, r in all_reports:
        lines.append(format_diagnostic_report(r))
        lines.append("")

    any_issues = [r for _, _, r in all_reports if r.issues]
    lines.append("## Overall Assessment")
    lines.append("")
    if not any_issues:
        lines.append("All datasets pass quality checks. Data is ready for campaign execution.")
    else:
        lines.append("Issues detected in the following datasets:")
        for pair_str, tf_str, r in all_reports:
            if r.issues:
                lines.append(f"- **{pair_str}/{tf_str}**: {'; '.join(r.issues)}")

    min_quality = min((r.quality_score for _, _, r in all_reports), default=0)
    lines.append(f"\n**Minimum quality score**: {min_quality:.3f}")
    lines.append(f"**Verdict**: {'READY' if min_quality >= 0.7 else 'REVIEW NEEDED'}")

    report_path = output_dir / "data_readiness_report.md"
    report_path.write_text("\n".join(lines))
    logger.info("Readiness report saved to %s", report_path)

    # Summary
    total_bars = sum(r.total_bars for _, _, r in all_reports)
    logger.info("=== Download complete: %d total bars across %d datasets ===", total_bars, len(all_reports))


if __name__ == "__main__":
    main()
