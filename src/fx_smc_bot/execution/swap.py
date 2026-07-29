"""Swap/financing cost calculation for overnight positions.

FX swap rates are the cost (or credit) of holding a position past the
daily rollover time (typically 17:00 New York / ~21:00-22:00 UTC).
Wednesday positions incur triple swap to cover the weekend.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fx_smc_bot.config import TradingPair
from fx_smc_bot.data.timezone import fx_trading_day_boundaries_dst


@dataclass(frozen=True, slots=True)
class SwapRate:
    """Swap rates in USD per standard lot per day."""

    pair: TradingPair
    long_rate: float
    short_rate: float


DEFAULT_SWAP_RATES: dict[TradingPair, SwapRate] = {
    TradingPair.EURUSD: SwapRate(TradingPair.EURUSD, long_rate=-7.0, short_rate=3.5),
    TradingPair.GBPUSD: SwapRate(TradingPair.GBPUSD, long_rate=-6.0, short_rate=2.5),
    TradingPair.USDJPY: SwapRate(TradingPair.USDJPY, long_rate=5.0, short_rate=-8.0),
    TradingPair.GBPJPY: SwapRate(TradingPair.GBPJPY, long_rate=3.0, short_rate=-10.0),
}


class SwapCalculator:
    """Computes swap charges for positions held across rollover."""

    def __init__(
        self,
        rates: dict[TradingPair, SwapRate] | None = None,
        lot_size: float = 100_000.0,
    ) -> None:
        self._rates = rates or DEFAULT_SWAP_RATES
        self._lot_size = lot_size

    def daily_swap(
        self,
        pair: TradingPair,
        direction: str,
        units: float,
        day_of_week: int,
    ) -> float:
        """Compute swap charge for one day.

        Parameters
        ----------
        pair : trading pair
        direction : "long" or "short"
        units : position size in base units
        day_of_week : 0=Monday through 6=Sunday

        Returns
        -------
        Swap cost in quote currency (negative = cost, positive = credit).
        """
        rate_obj = self._rates.get(pair)
        if rate_obj is None:
            return 0.0

        per_lot = rate_obj.long_rate if direction == "long" else rate_obj.short_rate
        lots = units / self._lot_size

        multiplier = 3 if day_of_week == 2 else 1  # triple Wednesday
        return per_lot * lots * multiplier

    def crosses_rollover(
        self,
        prev_bar_time: datetime,
        current_bar_time: datetime,
    ) -> bool:
        """Check if a rollover boundary falls between two bar times."""
        prev_day_start, prev_day_end = fx_trading_day_boundaries_dst(prev_bar_time)
        curr_day_start, _ = fx_trading_day_boundaries_dst(current_bar_time)
        return curr_day_start > prev_day_start
