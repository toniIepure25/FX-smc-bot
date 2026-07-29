"""Liquidity pool detection: equal highs/lows, prior session/day/week levels.

Liquidity pools are price levels where stop orders are likely clustered.
SMC/ICT theory holds that price is drawn to these levels to "sweep" liquidity
before reversing.

Detection methods:
  1. **Equal highs/lows**: clusters of swing points at similar prices
  2. **Prior period levels**: session, day, week highs and lows
  3. **Sweep detection**: price briefly pierces a level then reverses
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
from numpy.typing import NDArray

from fx_smc_bot.config import PAIR_PIP_INFO, StructureConfig, TradingPair
from fx_smc_bot.domain import (
    LiquidityLevel,
    LiquidityLevelType,
    SessionName,
    SessionWindow,
    SwingPoint,
    SwingType,
)
from fx_smc_bot.utils.math import pips_to_price
from fx_smc_bot.utils.time import trading_day_boundaries, trading_week_boundaries


def detect_equal_levels(
    swings: list[SwingPoint],
    pair: TradingPair,
    config: StructureConfig | None = None,
) -> list[LiquidityLevel]:
    """Find clusters of swing highs or swing lows at similar price levels.

    Two swing highs are "equal" if their prices differ by less than
    `equal_level_tolerance_pips`.  Clusters with >= `equal_level_min_touches`
    become liquidity levels.
    """
    cfg = config or StructureConfig()
    tolerance = pips_to_price(cfg.equal_level_tolerance_pips, pair)
    min_touches = cfg.equal_level_min_touches

    highs = [s for s in swings if s.swing_type == SwingType.HIGH]
    lows = [s for s in swings if s.swing_type == SwingType.LOW]

    levels: list[LiquidityLevel] = []
    levels.extend(_cluster_swings(highs, tolerance, min_touches, LiquidityLevelType.EQUAL_HIGHS))
    levels.extend(_cluster_swings(lows, tolerance, min_touches, LiquidityLevelType.EQUAL_LOWS))
    return levels


def _cluster_swings(
    swings: list[SwingPoint],
    tolerance: float,
    min_touches: int,
    level_type: LiquidityLevelType,
) -> list[LiquidityLevel]:
    """Greedy clustering of swing points by price proximity."""
    if not swings:
        return []

    sorted_swings = sorted(swings, key=lambda s: s.price)
    clusters: list[list[SwingPoint]] = []
    current_cluster = [sorted_swings[0]]

    for s in sorted_swings[1:]:
        if abs(s.price - current_cluster[-1].price) <= tolerance:
            current_cluster.append(s)
        else:
            if len(current_cluster) >= min_touches:
                clusters.append(current_cluster)
            current_cluster = [s]

    if len(current_cluster) >= min_touches:
        clusters.append(current_cluster)

    levels: list[LiquidityLevel] = []
    for cluster in clusters:
        avg_price = sum(s.price for s in cluster) / len(cluster)
        earliest = min(cluster, key=lambda s: s.bar_index)
        levels.append(LiquidityLevel(
            price=avg_price,
            level_type=level_type,
            touch_count=len(cluster),
            formation_index=earliest.bar_index,
            formation_time=earliest.timestamp,
        ))

    return levels


def detect_session_levels(
    session_windows: list[SessionWindow],
    current_bar_index: int,
) -> list[LiquidityLevel]:
    """Convert completed session windows into liquidity levels.

    A session high/low is only treated as a known level after the session
    window has ended.  This is determined by checking whether the current
    bar index is beyond the session's last bar (high_index and low_index
    are within the session, so we require current_bar_index > max of those).
    """
    levels: list[LiquidityLevel] = []
    for w in session_windows:
        last_session_bar = max(w.high_index, w.low_index)
        if last_session_bar < 0 or current_bar_index <= last_session_bar:
            continue

        if w.high > 0:
            levels.append(LiquidityLevel(
                price=w.high,
                level_type=LiquidityLevelType.SESSION_HIGH,
                touch_count=1,
                formation_index=w.high_index,
                formation_time=w.close_time,
            ))

        if w.low < float("inf"):
            levels.append(LiquidityLevel(
                price=w.low,
                level_type=LiquidityLevelType.SESSION_LOW,
                touch_count=1,
                formation_index=w.low_index,
                formation_time=w.close_time,
            ))

    return levels


def detect_daily_levels(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    timestamps: NDArray[np.datetime64],
    current_bar_index: int,
) -> list[LiquidityLevel]:
    """Detect prior-day high/low levels.

    Groups bars by FX trading day (21:00 UTC pivot) and creates
    liquidity levels from completed days only.
    """
    if len(timestamps) < 2:
        return []

    days: dict[str, dict] = {}
    for i in range(min(current_bar_index + 1, len(timestamps))):
        ts_dt = timestamps[i].astype("datetime64[us]").astype(datetime)
        day_start, day_end = trading_day_boundaries(ts_dt)
        key = day_start.isoformat()

        if key not in days:
            days[key] = {
                "high": float(high[i]), "low": float(low[i]),
                "high_idx": i, "low_idx": i,
                "end": day_end, "last_bar": i,
            }
        else:
            d = days[key]
            d["last_bar"] = i
            if high[i] > d["high"]:
                d["high"] = float(high[i])
                d["high_idx"] = i
            if low[i] < d["low"]:
                d["low"] = float(low[i])
                d["low_idx"] = i

    levels: list[LiquidityLevel] = []
    ts_current = timestamps[current_bar_index].astype("datetime64[us]").astype(datetime)

    for key, d in sorted(days.items()):
        if d["last_bar"] >= current_bar_index:
            continue
        formation_time = d["end"]

        levels.append(LiquidityLevel(
            price=d["high"],
            level_type=LiquidityLevelType.PRIOR_DAY_HIGH,
            touch_count=1,
            formation_index=d["high_idx"],
            formation_time=formation_time,
        ))
        levels.append(LiquidityLevel(
            price=d["low"],
            level_type=LiquidityLevelType.PRIOR_DAY_LOW,
            touch_count=1,
            formation_index=d["low_idx"],
            formation_time=formation_time,
        ))

    return levels


def detect_weekly_levels(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    timestamps: NDArray[np.datetime64],
    current_bar_index: int,
) -> list[LiquidityLevel]:
    """Detect prior-week high/low levels.

    Groups bars by FX trading week (Sunday 21:00 to Friday 21:00 UTC)
    and creates liquidity levels from completed weeks only.
    """
    if len(timestamps) < 2:
        return []

    weeks: dict[str, dict] = {}
    for i in range(min(current_bar_index + 1, len(timestamps))):
        ts_dt = timestamps[i].astype("datetime64[us]").astype(datetime)
        week_start, week_end = trading_week_boundaries(ts_dt)
        key = week_start.isoformat()

        if key not in weeks:
            weeks[key] = {
                "high": float(high[i]), "low": float(low[i]),
                "high_idx": i, "low_idx": i,
                "end": week_end, "last_bar": i,
            }
        else:
            w = weeks[key]
            w["last_bar"] = i
            if high[i] > w["high"]:
                w["high"] = float(high[i])
                w["high_idx"] = i
            if low[i] < w["low"]:
                w["low"] = float(low[i])
                w["low_idx"] = i

    levels: list[LiquidityLevel] = []
    for key, w in sorted(weeks.items()):
        if w["last_bar"] >= current_bar_index:
            continue

        levels.append(LiquidityLevel(
            price=w["high"],
            level_type=LiquidityLevelType.PRIOR_WEEK_HIGH,
            touch_count=1,
            formation_index=w["high_idx"],
            formation_time=w["end"],
        ))
        levels.append(LiquidityLevel(
            price=w["low"],
            level_type=LiquidityLevelType.PRIOR_WEEK_LOW,
            touch_count=1,
            formation_index=w["low_idx"],
            formation_time=w["end"],
        ))

    return levels


def detect_sweeps(
    levels: list[LiquidityLevel],
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
    timestamps: NDArray[np.datetime64],
    from_bar: int = 0,
) -> list[LiquidityLevel]:
    """Check if any liquidity levels have been swept.

    A sweep occurs when price pierces the level intrabar (wick) but closes
    back on the other side, indicating a stop hunt / liquidity grab.
    """
    updated: list[LiquidityLevel] = []
    for lev in levels:
        if lev.swept:
            updated.append(lev)
            continue

        start = max(from_bar, lev.formation_index + 1)
        swept = False
        sweep_idx: int | None = None

        for i in range(start, len(close)):
            if lev.level_type in (LiquidityLevelType.EQUAL_HIGHS,
                                  LiquidityLevelType.SESSION_HIGH,
                                  LiquidityLevelType.PRIOR_DAY_HIGH,
                                  LiquidityLevelType.PRIOR_WEEK_HIGH):
                if high[i] > lev.price and close[i] < lev.price:
                    swept = True
                    sweep_idx = i
                    break
            else:
                if low[i] < lev.price and close[i] > lev.price:
                    swept = True
                    sweep_idx = i
                    break

        if swept:
            updated.append(LiquidityLevel(
                price=lev.price, level_type=lev.level_type,
                touch_count=lev.touch_count,
                formation_index=lev.formation_index,
                formation_time=lev.formation_time,
                swept=True, sweep_index=sweep_idx,
            ))
        else:
            updated.append(lev)

    return updated
