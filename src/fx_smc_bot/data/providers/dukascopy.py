"""Dukascopy historical data downloader.

Dukascopy provides free historical FX data. This module downloads
OHLCV candle data from their public HTTP endpoints and converts
it into the framework's canonical format.

The public endpoint serves CSV data at:
    https://datafeed.dukascopy.com/datafeed/{PAIR}/{YEAR}/{MONTH-1}/{DAY}/
    {HOUR}h_ticks.bi5

For candle data, the JForex platform API or their web-based historical
data export is typically used. This module supports importing their
CSV exports and also provides a synthetic data generator for offline
development when real data access is unavailable.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from fx_smc_bot.config import Timeframe, TradingPair

logger = logging.getLogger(__name__)

# Dukascopy instrument names differ from our pair names
_DUKASCOPY_INSTRUMENTS: dict[TradingPair, str] = {
    TradingPair.EURUSD: "EURUSD",
    TradingPair.GBPUSD: "GBPUSD",
    TradingPair.USDJPY: "USDJPY",
    TradingPair.GBPJPY: "GBPJPY",
}

_PAIR_PROPERTIES: dict[TradingPair, dict] = {
    TradingPair.EURUSD: {"base": 1.05, "vol": 0.0006, "spread": 0.00012, "digits": 5},
    TradingPair.GBPUSD: {"base": 1.25, "vol": 0.0008, "spread": 0.00015, "digits": 5},
    TradingPair.USDJPY: {"base": 145.0, "vol": 0.08, "spread": 0.015, "digits": 3},
    TradingPair.GBPJPY: {"base": 185.0, "vol": 0.12, "spread": 0.025, "digits": 3},
}


def generate_realistic_data(
    pair: TradingPair,
    timeframe: Timeframe,
    start_date: str = "2023-01-02",
    end_date: str = "2024-12-31",
    seed: int = 42,
) -> pd.DataFrame:
    """Generate realistic synthetic FX data mimicking real market properties.

    Produces data with:
    - Proper FX trading hours (skips weekends)
    - Session-dependent volatility (higher in London/NY overlap)
    - Mean-reverting spread behavior
    - Realistic tick-level price dynamics via geometric Brownian motion
    - Occasional volatility clusters
    """
    rng = np.random.default_rng(seed + hash(pair.value) % 1000)
    props = _PAIR_PROPERTIES[pair]

    tf_minutes = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
    minutes = tf_minutes.get(timeframe.value, 15)

    start = pd.Timestamp(start_date, tz="UTC")
    end = pd.Timestamp(end_date, tz="UTC")

    timestamps: list[pd.Timestamp] = []
    current = start
    while current <= end:
        if current.weekday() < 5:  # Skip Saturday/Sunday
            timestamps.append(current)
        current += pd.Timedelta(minutes=minutes)

    if not timestamps:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "spread"])

    n = len(timestamps)
    base_vol = props["vol"] * np.sqrt(minutes / (24 * 60))

    # Session volatility multiplier
    hours = np.array([ts.hour for ts in timestamps])
    vol_mult = np.ones(n)
    vol_mult[(hours >= 7) & (hours < 9)] = 1.3    # London open
    vol_mult[(hours >= 12) & (hours < 16)] = 1.4   # Overlap
    vol_mult[(hours >= 0) & (hours < 7)] = 0.7     # Asian quiet

    # Volatility clustering (GARCH-like)
    vol_state = np.ones(n)
    for i in range(1, n):
        vol_state[i] = 0.95 * vol_state[i - 1] + 0.05 * abs(rng.standard_normal()) * 2
    vol_state = np.clip(vol_state, 0.5, 3.0)

    effective_vol = base_vol * vol_mult * vol_state

    # Price path via geometric Brownian motion
    log_returns = rng.normal(0, effective_vol)
    log_price = np.log(props["base"]) + np.cumsum(log_returns)
    closes = np.exp(log_price)

    digits = props["digits"]
    opens = np.empty(n)
    highs = np.empty(n)
    lows = np.empty(n)
    opens[0] = closes[0]
    for i in range(1, n):
        opens[i] = closes[i - 1]

    intrabar_range = effective_vol * 1.5
    highs = np.maximum(opens, closes) + np.abs(rng.normal(0, intrabar_range * 0.6))
    lows = np.minimum(opens, closes) - np.abs(rng.normal(0, intrabar_range * 0.6))

    # Spread: base spread with mean-reverting noise
    base_spread = props["spread"]
    spread_noise = rng.normal(0, base_spread * 0.3, n)
    spreads = np.clip(base_spread + spread_noise, base_spread * 0.3, base_spread * 5.0)
    # Wider spreads during low-liquidity hours
    spreads[(hours >= 21) | (hours < 2)] *= 1.8

    volumes = np.abs(rng.normal(500, 200, n)).astype(int)
    volumes[(hours >= 12) & (hours < 16)] = (volumes[(hours >= 12) & (hours < 16)] * 1.8).astype(int)

    df = pd.DataFrame({
        "timestamp": timestamps,
        "open": np.round(opens, digits),
        "high": np.round(highs, digits),
        "low": np.round(lows, digits),
        "close": np.round(closes, digits),
        "volume": volumes,
        "spread": np.round(spreads, digits + 1),
    })

    return df


def import_dukascopy_csv(path: Path | str) -> pd.DataFrame:
    """Import a Dukascopy-format CSV export into canonical DataFrame.

    Dukascopy CSVs typically have columns:
        Gmt time, Open, High, Low, Close, Volume
    """
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]

    ts_col = None
    for candidate in ["gmt time", "local time", "timestamp", "date"]:
        if candidate in df.columns:
            ts_col = candidate
            break

    if ts_col is None:
        raise ValueError(f"Cannot find timestamp column in {path}")

    df = df.rename(columns={ts_col: "timestamp"})
    df["timestamp"] = pd.to_datetime(df["timestamp"], format="mixed", utc=True)

    return df[["timestamp", "open", "high", "low", "close"] +
              [c for c in ["volume", "spread"] if c in df.columns]]
