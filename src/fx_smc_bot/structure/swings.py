"""Swing high/low detection.

Implements a fractal-based swing detector with configurable lookback and
optional ATR-based minimum size filter.  The lookback parameter *n* means
a swing high requires bar[i].high >= all bars in [i-n, i+n].

This is the foundation for all higher-level structure analysis (BOS, CHoCH,
liquidity, etc.).
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
from numpy.typing import NDArray

from fx_smc_bot.config import StructureConfig
from fx_smc_bot.domain import SwingPoint, SwingType
from fx_smc_bot.utils.math import atr as compute_atr


def detect_swings(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
    timestamps: NDArray[np.datetime64],
    config: StructureConfig | None = None,
) -> list[SwingPoint]:
    """Detect swing highs and lows using a fractal lookback method.

    Parameters
    ----------
    high, low, close : 1-D float arrays of equal length.
    timestamps : aligned datetime64 array.
    config : structure configuration (uses defaults if None).

    Returns
    -------
    List of SwingPoint, sorted by bar_index.
    """
    cfg = config or StructureConfig()
    n = cfg.swing_lookback
    length = len(high)
    if length < 2 * n + 1:
        return []

    atr_values = compute_atr(high, low, close, period=cfg.atr_period)
    min_size = cfg.min_swing_atr_multiple

    swings: list[SwingPoint] = []

    for i in range(n, length - n):
        # --- Swing high ---
        is_sh = True
        for j in range(i - n, i + n + 1):
            if j == i:
                continue
            if high[j] > high[i]:
                is_sh = False
                break
        if is_sh and min_size > 0 and atr_values[i] > 0:
            # Swing must be at least min_size * ATR above the lowest low in the window
            local_low = np.min(low[i - n: i + n + 1])
            if (high[i] - local_low) < min_size * atr_values[i]:
                is_sh = False

        if is_sh:
            strength = _swing_strength(high, i, n, is_high=True)
            ts = timestamps[i].astype("datetime64[us]").astype(datetime)
            swings.append(SwingPoint(
                bar_index=i, price=float(high[i]),
                swing_type=SwingType.HIGH, timestamp=ts,
                strength=strength,
            ))

        # --- Swing low ---
        is_sl = True
        for j in range(i - n, i + n + 1):
            if j == i:
                continue
            if low[j] < low[i]:
                is_sl = False
                break
        if is_sl and min_size > 0 and atr_values[i] > 0:
            local_high = np.max(high[i - n: i + n + 1])
            if (local_high - low[i]) < min_size * atr_values[i]:
                is_sl = False

        if is_sl:
            strength = _swing_strength(low, i, n, is_high=False)
            ts = timestamps[i].astype("datetime64[us]").astype(datetime)
            swings.append(SwingPoint(
                bar_index=i, price=float(low[i]),
                swing_type=SwingType.LOW, timestamp=ts,
                strength=strength,
            ))

    swings.sort(key=lambda s: s.bar_index)
    return swings


def _swing_strength(
    arr: NDArray[np.float64],
    idx: int,
    base_lookback: int,
    is_high: bool,
) -> int:
    """Count how many additional bars beyond the base lookback respect the swing.

    Strength 1 = exactly the base lookback qualifies.
    Higher values mean the swing dominates a wider region.
    """
    length = len(arr)
    strength = 1
    max_extra = min(base_lookback * 3, 30)
    for extra in range(1, max_extra + 1):
        left = idx - base_lookback - extra
        right = idx + base_lookback + extra
        if left < 0 or right >= length:
            break
        if is_high:
            if arr[left] > arr[idx] or arr[right] > arr[idx]:
                break
        else:
            if arr[left] < arr[idx] or arr[right] < arr[idx]:
                break
        strength += 1
    return strength
