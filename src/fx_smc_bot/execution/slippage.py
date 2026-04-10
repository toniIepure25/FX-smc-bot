"""Slippage and spread models.

Slippage models apply realistic execution costs to fill prices.
Includes fixed, volatility-aware, and data-driven models.
"""

from __future__ import annotations

import random
from typing import Protocol, runtime_checkable

from fx_smc_bot.config import PAIR_PIP_INFO, ExecutionConfig, TradingPair
from fx_smc_bot.domain import Direction
from fx_smc_bot.utils.math import pips_to_price


@runtime_checkable
class SlippageModel(Protocol):
    def apply(
        self,
        price: float,
        direction: Direction,
        pair: TradingPair,
    ) -> tuple[float, float, float]:
        """Return (fill_price, spread_cost_per_unit, slippage_per_unit)."""
        ...


class FixedSpreadSlippage:
    """Fixed spread + fixed slippage in pips."""

    def __init__(self, config: ExecutionConfig | None = None) -> None:
        self._cfg = config or ExecutionConfig()

    def apply(
        self,
        price: float,
        direction: Direction,
        pair: TradingPair,
    ) -> tuple[float, float, float]:
        spread_price = pips_to_price(self._cfg.default_spread_pips, pair)
        slip_price = pips_to_price(self._cfg.slippage_pips, pair)

        half_spread = spread_price / 2.0
        if direction == Direction.LONG:
            fill_price = price + half_spread + slip_price
        else:
            fill_price = price - half_spread - slip_price

        return fill_price, spread_price, slip_price


class ZeroSlippage:
    """No execution costs (useful for benchmarking ideal performance)."""

    def apply(
        self,
        price: float,
        direction: Direction,
        pair: TradingPair,
    ) -> tuple[float, float, float]:
        return price, 0.0, 0.0


class VolatilitySlippage:
    """Spread and slippage scale with current ATR for realistic cost modeling.

    During high-volatility regimes, execution costs widen. During low-vol
    periods, they compress. This avoids the fiction of constant spread
    across all market conditions.
    """

    def __init__(
        self,
        config: ExecutionConfig | None = None,
        current_atr: float = 0.0,
    ) -> None:
        self._cfg = config or ExecutionConfig()
        self._atr = current_atr

    def set_atr(self, atr: float) -> None:
        self._atr = atr

    def apply(
        self,
        price: float,
        direction: Direction,
        pair: TradingPair,
    ) -> tuple[float, float, float]:
        if self._atr <= 0:
            return FixedSpreadSlippage(self._cfg).apply(price, direction, pair)

        spread_price = self._atr * self._cfg.volatility_spread_factor
        slip_price = self._atr * self._cfg.volatility_slippage_factor

        # Floor: never go below half the fixed spread
        min_spread = pips_to_price(self._cfg.default_spread_pips * 0.5, pair)
        spread_price = max(spread_price, min_spread)

        half_spread = spread_price / 2.0
        if direction == Direction.LONG:
            fill_price = price + half_spread + slip_price
        else:
            fill_price = price - half_spread - slip_price

        return fill_price, spread_price, slip_price


class SpreadFromDataSlippage:
    """Use actual spread column from bar data, with configurable slippage.

    When bar data includes a spread column (e.g., from Dukascopy), use
    the recorded spread rather than a model. Falls back to fixed spread
    if no data-spread is available.
    """

    def __init__(
        self,
        config: ExecutionConfig | None = None,
        bar_spread: float | None = None,
    ) -> None:
        self._cfg = config or ExecutionConfig()
        self._bar_spread = bar_spread

    def set_bar_spread(self, spread: float | None) -> None:
        self._bar_spread = spread

    def apply(
        self,
        price: float,
        direction: Direction,
        pair: TradingPair,
    ) -> tuple[float, float, float]:
        if self._bar_spread is not None and self._bar_spread > 0:
            spread_price = self._bar_spread
        else:
            spread_price = pips_to_price(self._cfg.default_spread_pips, pair)

        slip_price = pips_to_price(self._cfg.slippage_pips, pair)

        half_spread = spread_price / 2.0
        if direction == Direction.LONG:
            fill_price = price + half_spread + slip_price
        else:
            fill_price = price - half_spread - slip_price

        return fill_price, spread_price, slip_price
