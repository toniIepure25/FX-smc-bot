"""Shared detection helpers for intraday SMC strategies.

All functions are causal: they only use data up to and including the
current bar index. Symmetry between long and short is enforced.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from fx_smc_bot.domain import (
    Direction,
    FVGZone,
    LiquidityLevel,
    LiquidityLevelType,
    SwingPoint,
    SwingType,
)

HIGH_SIDE_TYPES = frozenset({
    LiquidityLevelType.EQUAL_HIGHS,
    LiquidityLevelType.SESSION_HIGH,
    LiquidityLevelType.PRIOR_DAY_HIGH,
    LiquidityLevelType.PRIOR_WEEK_HIGH,
})

LOW_SIDE_TYPES = frozenset({
    LiquidityLevelType.EQUAL_LOWS,
    LiquidityLevelType.SESSION_LOW,
    LiquidityLevelType.PRIOR_DAY_LOW,
    LiquidityLevelType.PRIOR_WEEK_LOW,
})


def sweep_direction(level: LiquidityLevel) -> Direction | None:
    """Determine the fade direction for a sweep of this level.

    High-side sweep -> SHORT reversal (fade the sweep).
    Low-side sweep -> LONG reversal (fade the sweep).
    """
    if level.level_type in HIGH_SIDE_TYPES:
        return Direction.SHORT
    if level.level_type in LOW_SIDE_TYPES:
        return Direction.LONG
    return None


def check_sweep(
    level: LiquidityLevel,
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    bar_idx: int,
    min_excursion: float,
) -> tuple[bool, float]:
    """Check if bar_idx breaches the level by the minimum excursion.

    Returns (is_sweep, sweep_extreme).
    For high-side levels: high must exceed level + excursion.
    For low-side levels: low must go below level - excursion.
    """
    if level.level_type in HIGH_SIDE_TYPES:
        extreme = float(high[bar_idx])
        breached = extreme > level.price + min_excursion
        return breached, extreme
    elif level.level_type in LOW_SIDE_TYPES:
        extreme = float(low[bar_idx])
        breached = extreme < level.price - min_excursion
        return breached, extreme
    return False, 0.0


def compute_min_excursion(
    atr: float,
    spread: float,
    k_atr: float = 0.5,
    k_spread: float = 2.0,
    min_pips_price: float = 0.0003,
) -> float:
    """Compute the minimum excursion for a sweep to qualify."""
    return max(k_atr * atr, k_spread * spread, min_pips_price)


def check_reclaim(
    level: LiquidityLevel,
    close: NDArray[np.float64],
    sweep_bar: int,
    bar_idx: int,
    max_bars: int,
) -> bool:
    """Check if price has reclaimed (closed back through) the level.

    For high-side levels (SHORT reversal): close must drop back below level.
    For low-side levels (LONG reversal): close must rise back above level.
    """
    if bar_idx - sweep_bar > max_bars:
        return False
    if bar_idx <= sweep_bar:
        return False

    if level.level_type in HIGH_SIDE_TYPES:
        return float(close[bar_idx]) < level.price
    elif level.level_type in LOW_SIDE_TYPES:
        return float(close[bar_idx]) > level.price
    return False


def find_causal_swing(
    swings: list[SwingPoint],
    direction: Direction,
    max_bar: int,
    swing_lookback: int,
) -> SwingPoint | None:
    """Find the most recent causally confirmed swing for MSS detection.

    For LONG direction (bullish reversal after sell-side sweep):
      look for the most recent swing HIGH confirmed before max_bar.
    For SHORT direction (bearish reversal after buy-side sweep):
      look for the most recent swing LOW confirmed before max_bar.

    A swing at pivot i is confirmed at bar i + swing_lookback.
    """
    target_type = SwingType.HIGH if direction == Direction.LONG else SwingType.LOW
    best: SwingPoint | None = None

    for s in swings:
        confirmation_bar = s.bar_index + swing_lookback
        if confirmation_bar > max_bar:
            continue
        if s.swing_type != target_type:
            continue
        if best is None or s.bar_index > best.bar_index:
            best = s

    return best


def check_mss(
    direction: Direction,
    close: NDArray[np.float64],
    bar_idx: int,
    swing: SwingPoint,
) -> bool:
    """Check if the current bar closes beyond the swing (Market Structure Shift).

    For LONG: close must be above the swing high price.
    For SHORT: close must be below the swing low price.
    """
    if direction == Direction.LONG:
        return float(close[bar_idx]) > swing.price
    else:
        return float(close[bar_idx]) < swing.price


def check_displacement(
    open_: NDArray[np.float64],
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
    bar_idx: int,
    direction: Direction,
    atr: float,
    median_body: float,
    body_ratio_threshold: float = 2.0,
    tr_ratio_threshold: float = 1.5,
    clv_threshold: float = 0.6,
) -> bool:
    """Check if the current bar qualifies as a displacement candle."""
    body = abs(float(close[bar_idx]) - float(open_[bar_idx]))
    range_ = float(high[bar_idx]) - float(low[bar_idx])
    if range_ <= 0 or atr <= 0:
        return False

    body_ratio = body / median_body if median_body > 0 else 0
    tr = max(
        range_,
        abs(float(high[bar_idx]) - float(close[bar_idx - 1])) if bar_idx > 0 else range_,
        abs(float(low[bar_idx]) - float(close[bar_idx - 1])) if bar_idx > 0 else range_,
    )
    tr_ratio = tr / atr

    clv = (float(close[bar_idx]) - float(low[bar_idx])) / range_
    if direction == Direction.SHORT:
        clv = (float(high[bar_idx]) - float(close[bar_idx])) / range_

    is_correct_direction = (
        (direction == Direction.LONG and close[bar_idx] > open_[bar_idx])
        or (direction == Direction.SHORT and close[bar_idx] < open_[bar_idx])
    )

    return (
        is_correct_direction
        and body_ratio >= body_ratio_threshold
        and tr_ratio >= tr_ratio_threshold
        and clv >= clv_threshold
    )


def find_qualifying_fvg(
    active_fvgs: list[FVGZone],
    direction: Direction,
    after_bar: int,
    min_atr_size: float = 0.3,
) -> FVGZone | None:
    """Find the first qualifying FVG created after a given bar."""
    candidates = [
        f for f in active_fvgs
        if f.direction == direction
        and not f.invalidated
        and f.bar_index > after_bar
        and f.size_atr >= min_atr_size
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda f: f.bar_index)


def compute_entry_sl_tp(
    fvg: FVGZone,
    direction: Direction,
    sweep_extreme: float,
    entry_pct: float = 0.5,
    target_r: float = 2.0,
    sl_buffer: float = 0.0003,
) -> tuple[float, float, float]:
    """Compute entry, stop-loss, and take-profit for a reversal trade.

    Entry: at entry_pct of the FVG (0.5 = midpoint).
    Stop: beyond the sweep extreme + buffer.
    Target: entry + target_r * risk distance.
    """
    if direction == Direction.LONG:
        entry = fvg.low + entry_pct * (fvg.high - fvg.low)
        stop = sweep_extreme - sl_buffer
        risk = entry - stop
        tp = entry + target_r * risk
    else:
        entry = fvg.high - entry_pct * (fvg.high - fvg.low)
        stop = sweep_extreme + sl_buffer
        risk = stop - entry
        tp = entry - target_r * risk

    return entry, stop, tp
