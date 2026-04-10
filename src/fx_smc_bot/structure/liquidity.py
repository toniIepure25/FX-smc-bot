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
    SwingPoint,
    SwingType,
)
from fx_smc_bot.utils.math import pips_to_price


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
