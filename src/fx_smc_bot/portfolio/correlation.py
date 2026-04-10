"""Pair correlation estimation and penalties.

Provides rolling correlation between pair returns and a penalty function
that discourages taking highly correlated co-directional positions.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from fx_smc_bot.config import TradingPair


def rolling_correlation(
    returns_a: NDArray[np.float64],
    returns_b: NDArray[np.float64],
    window: int = 60,
) -> NDArray[np.float64]:
    """Compute rolling Pearson correlation between two return series."""
    n = len(returns_a)
    corr = np.full(n, np.nan, dtype=np.float64)
    for i in range(window - 1, n):
        a = returns_a[i - window + 1: i + 1]
        b = returns_b[i - window + 1: i + 1]
        std_a = np.std(a)
        std_b = np.std(b)
        if std_a > 0 and std_b > 0:
            corr[i] = float(np.corrcoef(a, b)[0, 1])
        else:
            corr[i] = 0.0
    return corr


def correlation_penalty(
    corr: float,
    same_direction: bool,
    threshold: float = 0.7,
) -> float:
    """Penalty factor [0, 1] for correlated positions.

    Returns 1.0 if positions are highly correlated and co-directional
    (meaning we should reduce the second position), 0.0 if uncorrelated
    or counter-directional.
    """
    if not same_direction:
        return 0.0
    if abs(corr) < threshold:
        return 0.0
    return min((abs(corr) - threshold) / (1.0 - threshold), 1.0)
