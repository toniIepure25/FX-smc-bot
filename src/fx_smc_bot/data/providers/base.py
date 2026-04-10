"""Protocol definition for market data providers."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from fx_smc_bot.config import Timeframe, TradingPair
from fx_smc_bot.data.models import BarSeries


@runtime_checkable
class MarketDataProvider(Protocol):
    """Interface that all data sources must satisfy.

    Providers load raw OHLCV data for a given pair and timeframe.
    They do *not* perform validation or session labeling -- that is
    the responsibility of higher-level loaders.
    """

    def load(
        self,
        pair: TradingPair,
        timeframe: Timeframe,
        start: str | None = None,
        end: str | None = None,
    ) -> BarSeries:
        """Load bars for *pair* / *timeframe*, optionally bounded by ISO date strings."""
        ...

    def available_pairs(self) -> list[TradingPair]:
        """Return pairs for which data exists in this provider."""
        ...

    def available_timeframes(self, pair: TradingPair) -> list[Timeframe]:
        """Return timeframes available for *pair*."""
        ...
