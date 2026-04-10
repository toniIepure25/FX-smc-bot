"""Multi-format CSV normalizer.

Converts CSV files from common FX data sources (MetaTrader, Dukascopy,
generic OHLCV) into a canonical schema suitable for the framework.

Canonical schema columns:
    timestamp (datetime64[ns, UTC]), open, high, low, close, volume, spread
"""

from __future__ import annotations

import logging
from enum import Enum
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class CsvFormat(str, Enum):
    GENERIC = "generic"
    METATRADER = "metatrader"
    DUKASCOPY = "dukascopy"


# Column mappings per format -> canonical names
_COLUMN_MAPS: dict[CsvFormat, dict[str, str]] = {
    CsvFormat.GENERIC: {
        "timestamp": "timestamp", "date": "timestamp", "datetime": "timestamp",
        "open": "open", "high": "high", "low": "low", "close": "close",
        "volume": "volume", "spread": "spread", "tick_volume": "volume",
    },
    CsvFormat.METATRADER: {
        "<date>": "_date", "<time>": "_time",
        "date": "_date", "time": "_time",
        "<open>": "open", "<high>": "high", "<low>": "low",
        "<close>": "close", "<tickvol>": "volume", "<vol>": "volume",
        "<spread>": "spread",
        "open": "open", "high": "high", "low": "low", "close": "close",
        "tickvol": "volume", "vol": "volume", "spread": "spread",
    },
    CsvFormat.DUKASCOPY: {
        "gmt time": "timestamp", "local time": "timestamp",
        "open": "open", "high": "high", "low": "low", "close": "close",
        "volume": "volume",
    },
}


def detect_format(path: Path) -> CsvFormat:
    """Heuristically detect the CSV format from header row."""
    with open(path, "r") as f:
        header = f.readline().strip().lower()

    if "<date>" in header or "<open>" in header:
        return CsvFormat.METATRADER
    if "gmt time" in header or "local time" in header:
        return CsvFormat.DUKASCOPY
    return CsvFormat.GENERIC


def normalize_csv(
    path: Path | str,
    fmt: CsvFormat | None = None,
    pair_hint: str | None = None,
) -> pd.DataFrame:
    """Read a CSV file and return a DataFrame with canonical columns.

    Returns a DataFrame with columns:
        timestamp, open, high, low, close, volume (optional), spread (optional)
    sorted by timestamp, deduplicated, with UTC timestamps.
    """
    path = Path(path)
    if fmt is None:
        fmt = detect_format(path)

    logger.info("Normalizing %s as %s format", path.name, fmt.value)

    df = pd.read_csv(path, sep=None, engine="python")
    df.columns = [c.strip().lower() for c in df.columns]

    col_map = _COLUMN_MAPS[fmt]
    rename = {}
    for src_col in df.columns:
        if src_col in col_map:
            rename[src_col] = col_map[src_col]
    df = df.rename(columns=rename)

    if fmt == CsvFormat.METATRADER and "_date" in df.columns:
        if "_time" in df.columns:
            df["timestamp"] = pd.to_datetime(
                df["_date"].astype(str) + " " + df["_time"].astype(str),
                format="mixed", dayfirst=False,
            )
        else:
            df["timestamp"] = pd.to_datetime(df["_date"], format="mixed")
        df = df.drop(columns=[c for c in ["_date", "_time"] if c in df.columns])
    elif "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], format="mixed", utc=True)
    else:
        raise ValueError(f"Cannot find timestamp column in {path}")

    if df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")
    else:
        df["timestamp"] = df["timestamp"].dt.tz_convert("UTC")

    required = ["timestamp", "open", "high", "low", "close"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns after normalization: {missing}")

    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
    if "spread" in df.columns:
        df["spread"] = pd.to_numeric(df["spread"], errors="coerce")

    df = df.dropna(subset=["open", "high", "low", "close"])
    df = df.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")
    df = df.reset_index(drop=True)

    keep_cols = ["timestamp", "open", "high", "low", "close"]
    if "volume" in df.columns:
        keep_cols.append("volume")
    if "spread" in df.columns:
        keep_cols.append("spread")

    return df[keep_cols]


def save_parquet(df: pd.DataFrame, path: Path | str) -> Path:
    """Save a normalized DataFrame to Parquet with proper dtypes."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df = df.copy()
    if df["timestamp"].dt.tz is not None:
        df["timestamp"] = df["timestamp"].dt.tz_convert("UTC")
    df.to_parquet(path, engine="pyarrow", index=False)
    logger.info("Saved %d rows to %s", len(df), path)
    return path


def load_parquet(path: Path | str) -> pd.DataFrame:
    """Load a Parquet file and ensure canonical dtypes."""
    df = pd.read_parquet(path, engine="pyarrow")
    if "timestamp" in df.columns and df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")
    return df
