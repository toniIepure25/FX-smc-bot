"""Regime classifiers: categorise market state from price data.

Provides volatility-based, trend/range, spread, and composite regime
classifiers. All implement the RegimeClassifier protocol.
"""

from __future__ import annotations

from enum import Enum
from typing import Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray

from fx_smc_bot.utils.math import atr as compute_atr, rolling_std


class MarketRegime(str, Enum):
    LOW_VOLATILITY = "low_vol"
    NORMAL = "normal"
    HIGH_VOLATILITY = "high_vol"
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    TRENDING = "trending"
    COMPRESSED = "compressed"
    EXPANDING = "expanding"
    TIGHT_SPREAD = "tight_spread"
    WIDE_SPREAD = "wide_spread"


@runtime_checkable
class RegimeClassifier(Protocol):
    def classify(
        self,
        high: NDArray[np.float64],
        low: NDArray[np.float64],
        close: NDArray[np.float64],
        bar_index: int,
    ) -> MarketRegime: ...


class VolatilityRegimeClassifier:
    """ATR-percentile-based volatility regime with optional trend overlay."""

    def __init__(
        self,
        atr_period: int = 14,
        lookback: int = 100,
        low_pctile: float = 25.0,
        high_pctile: float = 75.0,
        ma_period: int = 50,
    ) -> None:
        self._atr_period = atr_period
        self._lookback = lookback
        self._low_pctile = low_pctile
        self._high_pctile = high_pctile
        self._ma_period = ma_period

    def classify(
        self,
        high: NDArray[np.float64],
        low: NDArray[np.float64],
        close: NDArray[np.float64],
        bar_index: int,
    ) -> MarketRegime:
        atr_vals = compute_atr(high, low, close, self._atr_period)
        start = max(0, bar_index - self._lookback)
        window = atr_vals[start: bar_index + 1]

        current_atr = atr_vals[bar_index]
        low_threshold = float(np.percentile(window, self._low_pctile))
        high_threshold = float(np.percentile(window, self._high_pctile))

        if bar_index >= self._ma_period:
            ma = float(np.mean(close[bar_index - self._ma_period + 1: bar_index + 1]))
            if close[bar_index] > ma * 1.005:
                return MarketRegime.TRENDING_UP
            if close[bar_index] < ma * 0.995:
                return MarketRegime.TRENDING_DOWN

        if current_atr <= low_threshold:
            return MarketRegime.LOW_VOLATILITY
        if current_atr >= high_threshold:
            return MarketRegime.HIGH_VOLATILITY
        return MarketRegime.NORMAL


class TrendRangeClassifier:
    """Classifies whether the market is trending or ranging using
    directional persistence (net move / sum of absolute moves)."""

    def __init__(self, period: int = 20, trend_threshold: float = 0.4) -> None:
        self._period = period
        self._threshold = trend_threshold

    def classify(
        self,
        high: NDArray[np.float64],
        low: NDArray[np.float64],
        close: NDArray[np.float64],
        bar_index: int,
    ) -> MarketRegime:
        if bar_index < self._period:
            return MarketRegime.RANGING

        window = close[bar_index - self._period:bar_index + 1]
        abs_moves = float(np.sum(np.abs(np.diff(window))))
        net_move = abs(float(window[-1] - window[0]))
        persistence = net_move / abs_moves if abs_moves > 0 else 0.0

        if persistence >= self._threshold:
            if window[-1] > window[0]:
                return MarketRegime.TRENDING_UP
            return MarketRegime.TRENDING_DOWN
        return MarketRegime.RANGING


class SpreadRegimeClassifier:
    """Classifies spread conditions as tight, normal, or wide
    by comparing current range to rolling median range."""

    def __init__(self, lookback: int = 50, tight_pct: float = 30.0, wide_pct: float = 70.0) -> None:
        self._lookback = lookback
        self._tight_pct = tight_pct
        self._wide_pct = wide_pct

    def classify(
        self,
        high: NDArray[np.float64],
        low: NDArray[np.float64],
        close: NDArray[np.float64],
        bar_index: int,
    ) -> MarketRegime:
        ranges = high - low
        start = max(0, bar_index - self._lookback)
        window = ranges[start:bar_index + 1]
        current = ranges[bar_index]

        if len(window) < 2:
            return MarketRegime.NORMAL

        tight = float(np.percentile(window, self._tight_pct))
        wide = float(np.percentile(window, self._wide_pct))

        if current <= tight:
            return MarketRegime.TIGHT_SPREAD
        if current >= wide:
            return MarketRegime.WIDE_SPREAD
        return MarketRegime.NORMAL


class CompositeRegimeClassifier:
    """Combines multiple classifiers into a single regime string."""

    def __init__(self, classifiers: list[tuple[str, RegimeClassifier]] | None = None) -> None:
        if classifiers is None:
            classifiers = [
                ("vol", VolatilityRegimeClassifier()),
                ("trend", TrendRangeClassifier()),
            ]
        self._classifiers = classifiers

    def classify(
        self,
        high: NDArray[np.float64],
        low: NDArray[np.float64],
        close: NDArray[np.float64],
        bar_index: int,
    ) -> MarketRegime:
        parts = []
        for name, clf in self._classifiers:
            regime = clf.classify(high, low, close, bar_index)
            parts.append(regime.value)
        combined = "+".join(parts)
        try:
            return MarketRegime(combined)
        except ValueError:
            return MarketRegime(parts[0]) if parts else MarketRegime.NORMAL

    def classify_composite(
        self,
        high: NDArray[np.float64],
        low: NDArray[np.float64],
        close: NDArray[np.float64],
        bar_index: int,
    ) -> str:
        """Return the full composite string (not constrained to enum)."""
        parts = []
        for name, clf in self._classifiers:
            regime = clf.classify(high, low, close, bar_index)
            parts.append(f"{name}:{regime.value}")
        return "|".join(parts)
