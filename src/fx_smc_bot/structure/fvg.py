"""Fair Value Gap (FVG) detection.

An FVG is a three-candle pattern where a gap exists between the wicks of
candle 1 and candle 3, meaning candle 2's body moved so aggressively that
price left an "unfair" gap.

Bullish FVG: candle_3.low > candle_1.high  (gap above)
Bearish FVG: candle_1.low > candle_3.high  (gap below)

Filters:
  - Minimum size as ATR multiple
  - Fill tracking: percentage of gap that has been revisited
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
from numpy.typing import NDArray

from fx_smc_bot.config import StructureConfig
from fx_smc_bot.domain import Direction, FVGZone
from fx_smc_bot.utils.math import atr as compute_atr


def detect_fvg(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
    timestamps: NDArray[np.datetime64],
    config: StructureConfig | None = None,
) -> list[FVGZone]:
    """Detect Fair Value Gaps in the price series.

    Returns FVG zones sorted by bar_index (the middle candle index).
    """
    cfg = config or StructureConfig()
    n = len(high)
    if n < 3:
        return []

    atr_vals = compute_atr(high, low, close, period=cfg.atr_period)
    zones: list[FVGZone] = []

    for i in range(1, n - 1):
        # Bullish FVG: gap between candle[i-1].high and candle[i+1].low
        if low[i + 1] > high[i - 1]:
            gap_low = float(high[i - 1])
            gap_high = float(low[i + 1])
            gap_size = gap_high - gap_low
            if atr_vals[i] > 0 and gap_size / atr_vals[i] >= cfg.fvg_min_atr_multiple:
                ts = timestamps[i].astype("datetime64[us]").astype(datetime)
                zones.append(FVGZone(
                    high=gap_high, low=gap_low, direction=Direction.LONG,
                    bar_index=i, timestamp=ts,
                    size_atr=float(gap_size / atr_vals[i]),
                ))

        # Bearish FVG: gap between candle[i+1].high and candle[i-1].low
        if high[i + 1] < low[i - 1]:
            gap_high = float(low[i - 1])
            gap_low = float(high[i + 1])
            gap_size = gap_high - gap_low
            if atr_vals[i] > 0 and gap_size / atr_vals[i] >= cfg.fvg_min_atr_multiple:
                ts = timestamps[i].astype("datetime64[us]").astype(datetime)
                zones.append(FVGZone(
                    high=gap_high, low=gap_low, direction=Direction.SHORT,
                    bar_index=i, timestamp=ts,
                    size_atr=float(gap_size / atr_vals[i]),
                ))

    return zones


def update_fvg_fill(
    zones: list[FVGZone],
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    up_to_bar: int,
    max_fill_pct: float = 0.5,
) -> list[FVGZone]:
    """Update fill percentages and invalidation status for active FVGs.

    Returns new list of FVGZone with updated fill_pct and invalidated flags.
    """
    updated: list[FVGZone] = []
    for fvg in zones:
        if fvg.invalidated:
            updated.append(fvg)
            continue

        start = fvg.bar_index + 2  # first bar after the FVG formation
        end = min(up_to_bar + 1, len(high))
        if start >= end:
            updated.append(fvg)
            continue

        gap_size = fvg.high - fvg.low
        if gap_size <= 0:
            updated.append(fvg)
            continue

        if fvg.direction == Direction.LONG:
            deepest_intrusion = np.min(low[start:end])
            fill_depth = max(0.0, fvg.high - deepest_intrusion)
        else:
            deepest_intrusion = np.max(high[start:end])
            fill_depth = max(0.0, deepest_intrusion - fvg.low)

        fill_pct = min(fill_depth / gap_size, 1.0)
        invalidated = fill_pct >= max_fill_pct

        updated.append(FVGZone(
            high=fvg.high, low=fvg.low, direction=fvg.direction,
            bar_index=fvg.bar_index, timestamp=fvg.timestamp,
            size_atr=fvg.size_atr, filled_pct=fill_pct,
            invalidated=invalidated,
        ))

    return updated
