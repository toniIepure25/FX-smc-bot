"""Deterministic, causal feature primitives for V2.

Every primitive here is *causal*: the value at bar ``t`` uses only information available
at the close of bar ``t`` (bars ``<= t``). Combined with the execution kernel's mandatory
one-completed-bar latency (a signal formed at close of ``t`` acts at the open of ``t+1``),
no primitive can leak future information.

All primitives operate on a canonical frame with columns ``timestamp`` (UTC, tz-aware),
``bid_*``/``ask_*``/``mid_*`` OHLC, ``spread`` and ``mid_return``. Use :func:`ensure_derived`
to guarantee the derived columns exist. The Dukascopy ``volume`` field is never read.
"""

from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from fx_smc_bot.research.v2.spec import FeatureKind

NY = ZoneInfo("America/New_York")

# Feature kind -> capability keys it requires. Used by the compiler for admissibility.
FEATURE_CAPABILITIES: dict[FeatureKind, tuple[str, ...]] = {
    FeatureKind.SESSION_MOMENTUM: (
        "MID_OHLC", "M1_RETURNS", "M1_REALIZED_VOL", "SESSION_TIME_OF_DAY"),
    FeatureKind.SIGNED_RETURN_RUN: ("MID_OHLC", "M1_RETURNS"),
    FeatureKind.VOLATILITY_BREAKOUT: (
        "MID_OHLC", "ROLLING_RANGE_M1", "WILDER_ATR_M1", "M1_REALIZED_VOL"),
    FeatureKind.RANGE_COMPRESSION_EXPANSION: ("MID_OHLC", "ROLLING_RANGE_M1"),
    FeatureKind.SPREAD_ZSCORE: ("M1_SPREAD", "MID_OHLC"),
    FeatureKind.LIQUIDITY_SHOCK_M1: ("M1_SPREAD", "MID_OHLC", "M1_RETURNS", "ROLLING_RANGE_M1"),
    FeatureKind.SEASONALITY_CELL: ("SESSION_TIME_OF_DAY", "CALENDAR_CELLS", "M1_RETURNS"),
    FeatureKind.REGIME_TREND: ("MID_OHLC", "M1_RETURNS", "M1_REALIZED_VOL"),
    FeatureKind.ML_ABSTENTION: ("MID_OHLC", "M1_RETURNS", "M1_REALIZED_VOL", "M1_SPREAD"),
}


def ensure_derived(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a frame guaranteeing mid_* / spread / mid_return columns (deterministic)."""

    out = frame.copy()
    if "mid_close" not in out:
        out["mid_close"] = (out["bid_close"] + out["ask_close"]) / 2.0
    if "mid_open" not in out:
        out["mid_open"] = (out["bid_open"] + out["ask_open"]) / 2.0
    if "mid_high" not in out:
        out["mid_high"] = (out["bid_high"] + out["ask_high"]) / 2.0
    if "mid_low" not in out:
        out["mid_low"] = (out["bid_low"] + out["ask_low"]) / 2.0
    if "spread" not in out:
        out["spread"] = out["ask_close"] - out["bid_close"]
    if "mid_return" not in out:
        out["mid_return"] = out["mid_close"].pct_change().fillna(0.0)
    return out


def _price(frame: pd.DataFrame, price_rep: str) -> pd.Series:
    col = {"mid": "mid_close", "bid": "bid_close", "ask": "ask_close"}[price_rep]
    return frame[col].astype(float)


def rolling_zscore(series: pd.Series, lookback: int, min_obs: int) -> pd.Series:
    """Causal rolling z-score: (x - trailing_mean) / trailing_std, ddof=0."""

    lookback = max(int(lookback), 2)
    mean = series.rolling(lookback, min_periods=min_obs).mean()
    std = series.rolling(lookback, min_periods=min_obs).std(ddof=0)
    z = (series - mean) / std.replace(0.0, np.nan)
    return z.fillna(0.0)


def mid_return_over(frame: pd.DataFrame, lookback: int, price_rep: str = "mid") -> pd.Series:
    """Percent change of price over ``lookback`` bars, causal, NaN->0 during warm-up."""

    return _price(frame, price_rep).pct_change(max(int(lookback), 1)).fillna(0.0)


def realized_vol(frame: pd.DataFrame, lookback: int) -> pd.Series:
    """Trailing standard deviation of 1-bar mid returns (realised-vol proxy, M1 scale)."""

    lookback = max(int(lookback), 2)
    return (
        frame["mid_return"].rolling(lookback, min_periods=max(3, lookback // 3)).std(ddof=0)
    ).fillna(0.0)


def wilder_atr(frame: pd.DataFrame, period: int, price_rep: str = "mid") -> pd.Series:
    """Wilder ATR from ``price_rep`` OHLC. Exact recursive definition.

    ``TR_t = max(high_t - low_t, |high_t - close_{t-1}|, |low_t - close_{t-1}|)``.
    Seeded by the simple mean of the first ``period`` true ranges, then Wilder-smoothed.
    Returns ATR in absolute price units (causal at bar ``t``).
    """

    period = max(int(period), 1)
    prefix = {"mid": "mid", "bid": "bid", "ask": "ask"}[price_rep]
    high = frame[f"{prefix}_high"].astype(float).to_numpy()
    low = frame[f"{prefix}_low"].astype(float).to_numpy()
    close = frame[f"{prefix}_close"].astype(float).to_numpy()
    n = len(close)
    atr = np.zeros(n, dtype=float)
    if n == 0:
        return pd.Series(atr, index=frame.index)
    tr = np.empty(n, dtype=float)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )
    seed = float(np.mean(tr[:period])) if n >= period else float(np.mean(tr[: max(n, 1)]))
    for i in range(n):
        if i < period:
            atr[i] = float(np.mean(tr[: i + 1]))
        elif i == period:
            atr[i] = seed
        else:
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return pd.Series(atr, index=frame.index)


def rolling_range(frame: pd.DataFrame, lookback: int, price_rep: str = "mid") -> pd.Series:
    """Trailing (max high - min low) over ``lookback`` bars, in absolute price units."""

    lookback = max(int(lookback), 1)
    prefix = {"mid": "mid", "bid": "bid", "ask": "ask"}[price_rep]
    high = frame[f"{prefix}_high"].rolling(lookback, min_periods=1).max()
    low = frame[f"{prefix}_low"].rolling(lookback, min_periods=1).min()
    return (high - low).astype(float)


def range_compression(frame: pd.DataFrame, short: int, long: int) -> pd.Series:
    """Ratio of a short trailing range to a long trailing range (dimensionless).

    Values ``< 1`` indicate compression (coiling), ``> 1`` indicate expansion.
    """

    short_range = rolling_range(frame, short)
    long_range = rolling_range(frame, long) / max(int(long) / max(int(short), 1), 1.0)
    ratio = short_range / long_range.replace(0.0, np.nan)
    return ratio.fillna(1.0)


def spread_bps(frame: pd.DataFrame) -> pd.Series:
    mid = frame["mid_close"].replace(0.0, np.nan)
    return (frame["spread"] / mid * 10_000.0).fillna(0.0)


def spread_zscore(frame: pd.DataFrame, lookback: int, min_obs: int) -> pd.Series:
    return rolling_zscore(spread_bps(frame), lookback, min_obs)


def ny_local(frame: pd.DataFrame) -> pd.DatetimeIndex:
    ts = pd.to_datetime(frame["timestamp"], utc=True)
    return ts.dt.tz_convert(NY)


def session_mask(frame: pd.DataFrame, anchor: str) -> pd.Series:
    """Boolean mask selecting the bars inside a named session-opening window (NY hours)."""

    hours = ny_local(frame).dt.hour
    anchor = anchor.lower()
    if anchor in ("all_day", "all"):
        return pd.Series(True, index=frame.index)
    if "tokyo" in anchor:
        sel = [19, 20, 21]
    elif "london_1600" in anchor or "london 16" in anchor or "fixing" in anchor:
        sel = [10, 11]
    elif "new_york" in anchor or "new york" in anchor:
        sel = [8, 9, 10]
    elif "london" in anchor:
        sel = [2, 3, 4]
    else:
        return pd.Series(False, index=frame.index)
    return hours.isin(sel)


def calendar_cell(frame: pd.DataFrame, cell: str) -> pd.Series:
    """Integer/boolean cell id for a seasonality cell kind (causal, timestamp-only)."""

    local = ny_local(frame)
    if cell == "hour_of_session":
        return local.dt.hour.astype(int)
    if cell == "day_of_week":
        return local.dt.dayofweek.astype(int)
    if cell == "month_end":
        return local.dt.is_month_end.astype(int)
    if cell == "quarter_end":
        return (local.dt.is_quarter_end).astype(int)
    raise ValueError(f"unknown seasonality cell {cell!r}")


def model_feature_panel(frame: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """Causal feature panel shared by regime (F11) and ML-abstention (F12) families.

    Columns are all known at the close of bar ``t`` and are unit-stable. No column reads
    the ``volume`` field or any future bar.
    """

    lookback = max(int(lookback), 2)
    panel = pd.DataFrame(index=frame.index)
    panel["ret_lb"] = mid_return_over(frame, lookback)
    panel["rvol_lb"] = realized_vol(frame, lookback)
    atr = wilder_atr(frame, lookback)
    panel["atr_norm"] = (atr / frame["mid_close"].replace(0.0, np.nan)).fillna(0.0)
    panel["range_comp"] = range_compression(frame, max(lookback // 2, 2), lookback * 3)
    panel["spread_z"] = spread_zscore(frame, lookback * 5, max(5, lookback))
    hour = ny_local(frame).dt.hour.to_numpy()
    panel["hour_sin"] = np.sin(2.0 * np.pi * hour / 24.0)
    panel["hour_cos"] = np.cos(2.0 * np.pi * hour / 24.0)
    return panel.fillna(0.0)


def primary_feature(frame: pd.DataFrame, kind: FeatureKind, extra: dict[str, Any]) -> pd.Series:
    """Dispatch a single normalised, causal feature series for simple (non-model) families."""

    lb = int(extra.get("lookback_bars", 30))
    if kind is FeatureKind.SIGNED_RETURN_RUN:
        run = np.sign(frame["mid_return"]).rolling(lb, min_periods=3).sum().fillna(0.0)
        return run / np.sqrt(max(lb, 1))
    if kind is FeatureKind.VOLATILITY_BREAKOUT:
        rng = rolling_range(frame, lb)
        atr = wilder_atr(frame, lb)
        return ((rng / atr.replace(0.0, np.nan)) - 1.0).fillna(0.0)
    if kind is FeatureKind.RANGE_COMPRESSION_EXPANSION:
        return range_compression(frame, max(lb // 2, 2), lb * 3) - 1.0
    if kind is FeatureKind.SPREAD_ZSCORE:
        return spread_zscore(frame, lb, max(5, lb // 3))
    if kind is FeatureKind.LIQUIDITY_SHOCK_M1:
        shock = spread_zscore(frame, lb, max(5, lb // 3))
        abn = rolling_zscore(frame["mid_return"].abs(), lb, max(3, lb // 3))
        return (shock + abn) / 2.0
    raise ValueError(f"primary_feature does not handle {kind!r}")
