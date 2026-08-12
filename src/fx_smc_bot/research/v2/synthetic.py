"""Deterministic synthetic fixtures for the V2 pre-discovery dry run.

These fixtures exist solely to verify the pipeline end-to-end without touching any 2018+
outcome. They are generated from a fixed seed and carry a pre-2018 timestamp span, so the
holdout firewall treats them as permitted. No dry-run number may influence the V2 search
space; the fixtures are for machinery verification only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd  # type: ignore[import-untyped]


def synthetic_frame(
    instrument: str,
    *,
    n_bars: int = 6000,
    seed: int = 20160301,
    start: str = "2016-03-07 00:00",
    jpy: bool | None = None,
) -> pd.DataFrame:
    """Build a deterministic M1 bid/ask OHLC frame with intraday structure.

    The mid path is a seeded random walk with a mild time-of-day volatility cycle; the
    spread widens outside the London/NY overlap. Prices are scaled for JPY vs non-JPY.
    """

    if jpy is None:
        jpy = instrument.endswith("JPY")
    rng = np.random.default_rng(seed + (hash(instrument) % 100000))
    idx = pd.date_range(start=start, periods=n_bars, freq="1min", tz="UTC")
    minutes = idx.hour.to_numpy() * 60 + idx.minute.to_numpy()
    tod_vol = 0.6 + 0.8 * (np.sin(2 * np.pi * minutes / 1440.0) ** 2)
    base = 110.0 if jpy else 1.10
    tick = 0.01 if jpy else 0.0001
    steps = rng.standard_normal(n_bars) * tod_vol * (2.0 * tick)
    mid_close = base + np.cumsum(steps)
    bar_range = np.abs(rng.standard_normal(n_bars)) * tod_vol * (1.5 * tick) + tick
    mid_open = np.empty(n_bars)
    mid_open[0] = mid_close[0]
    mid_open[1:] = mid_close[:-1]
    mid_high = np.maximum(mid_open, mid_close) + bar_range * 0.5
    mid_low = np.minimum(mid_open, mid_close) - bar_range * 0.5
    hours = idx.hour.to_numpy()
    overlap = (hours >= 12) & (hours < 16)
    half_spread = np.where(overlap, 0.4 * tick, 1.1 * tick) + 0.2 * tick * np.abs(
        rng.standard_normal(n_bars)
    )
    frame = pd.DataFrame({
        "timestamp": idx,
        "bid_open": mid_open - half_spread,
        "bid_high": mid_high - half_spread,
        "bid_low": mid_low - half_spread,
        "bid_close": mid_close - half_spread,
        "ask_open": mid_open + half_spread,
        "ask_high": mid_high + half_spread,
        "ask_low": mid_low + half_spread,
        "ask_close": mid_close + half_spread,
    })
    frame["mid_close"] = (frame["bid_close"] + frame["ask_close"]) / 2.0
    frame["mid_open"] = (frame["bid_open"] + frame["ask_open"]) / 2.0
    frame["mid_high"] = (frame["bid_high"] + frame["ask_high"]) / 2.0
    frame["mid_low"] = (frame["bid_low"] + frame["ask_low"]) / 2.0
    frame["spread"] = frame["ask_close"] - frame["bid_close"]
    frame["mid_return"] = frame["mid_close"].pct_change().fillna(0.0)
    return frame
