"""Numerical helpers: ATR, pip calculations, rolling statistics.

All functions operate on numpy arrays for performance.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from fx_smc_bot.config import PAIR_PIP_INFO, TradingPair


def true_range(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Compute True Range for each bar (first bar uses high-low)."""
    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]
    tr = np.maximum(
        high - low,
        np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)),
    )
    return tr


def atr(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
    period: int = 14,
) -> NDArray[np.float64]:
    """Wilder-smoothed Average True Range.

    Returns an array the same length as the input.  The first `period` values
    use a simple expanding mean so the output is always defined.
    """
    tr = true_range(high, low, close)
    out = np.empty_like(tr)
    if len(tr) == 0:
        return out

    out[0] = tr[0]
    alpha = 1.0 / period
    for i in range(1, len(tr)):
        if i < period:
            out[i] = np.mean(tr[: i + 1])
        else:
            out[i] = out[i - 1] * (1 - alpha) + tr[i] * alpha
    return out


def body_size(
    open_: NDArray[np.float64],
    close: NDArray[np.float64],
) -> NDArray[np.float64]:
    return np.abs(close - open_)


def bar_range(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
) -> NDArray[np.float64]:
    return high - low


def body_efficiency(
    open_: NDArray[np.float64],
    close: NDArray[np.float64],
    high: NDArray[np.float64],
    low: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Body / range ratio (0-1). Returns 0 where range is 0."""
    rng = bar_range(high, low)
    with np.errstate(divide="ignore", invalid="ignore"):
        eff = np.where(rng > 0, body_size(open_, close) / rng, 0.0)
    return eff


def price_to_pips(price_diff: float, pair: TradingPair) -> float:
    pip_size, _ = PAIR_PIP_INFO[pair]
    if pip_size == 0:
        return 0.0
    return price_diff / pip_size


def pips_to_price(pips: float, pair: TradingPair) -> float:
    pip_size, _ = PAIR_PIP_INFO[pair]
    return pips * pip_size


def pip_value_per_unit(pair: TradingPair, account_ccy: str = "USD") -> float:
    """Value of one pip for one unit of the pair.

    Simplified: assumes account currency is always USD.  For JPY-quoted pairs
    pip value depends on current exchange rate, which callers must handle.
    """
    _, quote = PAIR_PIP_INFO[pair]
    pip_size = PAIR_PIP_INFO[pair][0]
    if pair in (TradingPair.EURUSD, TradingPair.GBPUSD):
        return pip_size
    # For USD/JPY or GBP/JPY the pip value in USD requires division by the
    # current rate.  Return pip_size as a placeholder; callers scale by rate.
    return pip_size


def rolling_std(
    values: NDArray[np.float64],
    window: int,
) -> NDArray[np.float64]:
    """Simple rolling standard deviation. First `window-1` values use expanding window."""
    n = len(values)
    out = np.empty(n, dtype=np.float64)
    for i in range(n):
        start = max(0, i - window + 1)
        out[i] = np.std(values[start: i + 1], ddof=1) if (i - start) >= 1 else 0.0
    return out
