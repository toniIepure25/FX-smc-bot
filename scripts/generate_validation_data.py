#!/usr/bin/env python3
"""Generate realistic synthetic FX data for validation campaigns.

Produces 15-minute OHLCV data for EURUSD, GBPUSD, USDJPY with:
- realistic volatility profiles per pair
- session-based volume patterns (Asian/London/NY)
- mean-reverting microstructure within trends
- enough bars for meaningful train/val/holdout splits (~2000 bars per pair)
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PAIRS = {
    "EURUSD": {"base_price": 1.0850, "daily_vol": 0.0060, "pip": 0.0001},
    "GBPUSD": {"base_price": 1.2650, "daily_vol": 0.0080, "pip": 0.0001},
    "USDJPY": {"base_price": 151.50, "daily_vol": 0.80, "pip": 0.01},
}

N_DAYS = 120
BARS_PER_DAY = 96  # 15-min bars per 24h


def _session_volatility_multiplier(hour: int) -> float:
    """Session-based vol scaling: higher during London/NY overlap."""
    if 7 <= hour < 10:
        return 1.3  # London open
    if 12 <= hour < 16:
        return 1.5  # London/NY overlap
    if 16 <= hour < 21:
        return 1.1  # NY afternoon
    if 0 <= hour < 7:
        return 0.6  # Asian session
    return 0.8


def generate_pair_data(
    pair_name: str,
    base_price: float,
    daily_vol: float,
    pip: float,
    rng: np.random.Generator,
    n_days: int = N_DAYS,
) -> pd.DataFrame:
    """Generate one pair's 15-min OHLCV data."""
    n_bars = n_days * BARS_PER_DAY
    bar_vol = daily_vol / np.sqrt(BARS_PER_DAY)

    start = datetime(2024, 1, 2, 0, 0)
    delta = timedelta(minutes=15)

    timestamps = []
    opens = []
    highs = []
    lows = []
    closes = []
    volumes = []
    spreads = []

    price = base_price
    # Slow regime drift
    trend = 0.0

    for i in range(n_bars):
        ts = start + delta * i
        hour = ts.hour
        weekday = ts.weekday()

        # Skip weekends
        if weekday >= 5:
            continue

        session_mult = _session_volatility_multiplier(hour)
        vol = bar_vol * session_mult

        # Slow trend changes every ~2 weeks
        if i % (BARS_PER_DAY * 10) == 0:
            trend = rng.normal(0, daily_vol * 0.3)

        move = trend / BARS_PER_DAY + rng.normal(0, vol)

        # Mean reversion around 200-bar moving window
        if i > 200:
            mean_price = base_price + (price - base_price) * 0.999
            reversion = (mean_price - price) * 0.002
            move += reversion

        o = price
        c = o + move
        intra_vol = abs(move) + abs(rng.normal(0, vol * 0.5))
        h = max(o, c) + abs(rng.normal(0, intra_vol * 0.3))
        l = min(o, c) - abs(rng.normal(0, intra_vol * 0.3))

        # Ensure OHLC consistency
        h = max(h, o, c)
        l = min(l, o, c)

        # Volume: higher during active sessions
        base_vol = 1000 * session_mult
        vol_noise = rng.exponential(base_vol * 0.3)
        v = base_vol + vol_noise

        # Spread: tighter during active sessions
        sp = pip * (1.5 / session_mult + rng.exponential(0.3))

        timestamps.append(ts)
        opens.append(round(o, 5 if pip < 0.001 else 3))
        highs.append(round(h, 5 if pip < 0.001 else 3))
        lows.append(round(l, 5 if pip < 0.001 else 3))
        closes.append(round(c, 5 if pip < 0.001 else 3))
        volumes.append(round(v, 0))
        spreads.append(round(sp, 5 if pip < 0.001 else 3))

        price = c

    df = pd.DataFrame({
        "timestamp": timestamps,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
        "spread": spreads,
    })
    return df


def main() -> None:
    output_dir = Path(__file__).resolve().parent.parent / "data"
    rng = np.random.default_rng(42)

    for pair_name, params in PAIRS.items():
        pair_dir = output_dir / pair_name
        pair_dir.mkdir(parents=True, exist_ok=True)

        logger.info("Generating %s data...", pair_name)
        df = generate_pair_data(
            pair_name, params["base_price"], params["daily_vol"],
            params["pip"], rng,
        )

        csv_path = pair_dir / "15m.csv"
        df.to_csv(csv_path, index=False)
        logger.info("  Saved %d bars to %s", len(df), csv_path)

    logger.info("Data generation complete. Output: %s", output_dir)


if __name__ == "__main__":
    main()
