"""OHLC-derived microstructure proxies.

Computes bar-level features that proxy for market microstructure
dynamics without requiring tick data: efficiency, wick asymmetry,
spread stress, volatility compression, and directional persistence.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


def bar_efficiency(
    open_: NDArray[np.float64],
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Body-to-range ratio: 1.0 = pure trend bar, 0.0 = pure wick (doji).

    Measures how much of the bar's range was 'useful' directional movement.
    """
    body = np.abs(close - open_)
    range_ = high - low
    safe_range = np.where(range_ > 0, range_, 1.0)
    return np.clip(body / safe_range, 0.0, 1.0)


def wick_asymmetry(
    open_: NDArray[np.float64],
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Wick asymmetry: positive = upper wick dominant, negative = lower wick dominant.

    Range [-1, 1]. Near 0 means balanced or no wicks.
    """
    body_high = np.maximum(open_, close)
    body_low = np.minimum(open_, close)
    upper_wick = high - body_high
    lower_wick = body_low - low
    total_wick = upper_wick + lower_wick
    safe_total = np.where(total_wick > 0, total_wick, 1.0)
    return (upper_wick - lower_wick) / safe_total


def relative_spread_stress(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
    spread: NDArray[np.float64] | None = None,
    period: int = 14,
) -> NDArray[np.float64]:
    """Spread-to-range ratio as liquidity stress proxy.

    When spread is not available, uses 10% of ATR as a synthetic estimate.
    High values indicate tight/illiquid conditions.
    """
    range_ = high - low
    if spread is None:
        from fx_smc_bot.utils.math import atr as compute_atr
        atr_vals = compute_atr(high, low, close, period)
        spread = atr_vals * 0.10

    safe_range = np.where(range_ > 0, range_, 1.0)
    return np.clip(spread / safe_range, 0.0, 5.0)


def volatility_compression(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    short_period: int = 5,
    long_period: int = 20,
) -> NDArray[np.float64]:
    """Ratio of short-period to long-period average range.

    Values < 1.0 indicate compression (squeeze), > 1.0 indicates expansion.
    """
    range_ = high - low
    n = len(range_)
    result = np.ones(n, dtype=np.float64)
    for i in range(long_period, n):
        short_avg = float(np.mean(range_[max(0, i - short_period + 1):i + 1]))
        long_avg = float(np.mean(range_[max(0, i - long_period + 1):i + 1]))
        result[i] = short_avg / long_avg if long_avg > 0 else 1.0
    return result


def directional_persistence(
    close: NDArray[np.float64],
    period: int = 14,
) -> NDArray[np.float64]:
    """Choppiness-style measure: net move / sum of absolute moves.

    1.0 = perfectly trending, 0.0 = perfectly choppy.
    """
    n = len(close)
    result = np.zeros(n, dtype=np.float64)
    for i in range(period, n):
        window = close[i - period:i + 1]
        abs_moves = np.sum(np.abs(np.diff(window)))
        net_move = abs(window[-1] - window[0])
        result[i] = net_move / abs_moves if abs_moves > 0 else 0.0
    return result


def compute_all_proxies(
    open_: NDArray[np.float64],
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
    spread: NDArray[np.float64] | None = None,
) -> dict[str, NDArray[np.float64]]:
    """Compute all microstructure proxies as a dictionary."""
    return {
        "bar_efficiency": bar_efficiency(open_, high, low, close),
        "wick_asymmetry": wick_asymmetry(open_, high, low, close),
        "spread_stress": relative_spread_stress(high, low, close, spread),
        "vol_compression": volatility_compression(high, low),
        "dir_persistence": directional_persistence(close),
    }
