"""Bid/Ask bar series data model for research-grade execution simulation.

Preserves full bid and ask OHLC independently. Derived mid-price and spread
fields are computed on demand. Resampling keeps bid and ask channels separate.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from fx_smc_bot.config import Timeframe, TradingPair
from fx_smc_bot.data.models import BarSeries


@dataclass(slots=True)
class BidAskBarSeries:
    """Full bid/ask bar series for one pair and timeframe."""

    pair: TradingPair
    timeframe: Timeframe
    timestamps: NDArray[np.datetime64]
    bid_open: NDArray[np.float64]
    bid_high: NDArray[np.float64]
    bid_low: NDArray[np.float64]
    bid_close: NDArray[np.float64]
    ask_open: NDArray[np.float64]
    ask_high: NDArray[np.float64]
    ask_low: NDArray[np.float64]
    ask_close: NDArray[np.float64]
    volume: NDArray[np.float64] | None = None
    tick_volume: NDArray[np.float64] | None = None

    def __len__(self) -> int:
        return len(self.timestamps)

    def __post_init__(self) -> None:
        n = len(self.timestamps)
        for name in (
            "bid_open", "bid_high", "bid_low", "bid_close",
            "ask_open", "ask_high", "ask_low", "ask_close",
        ):
            arr = getattr(self, name)
            if len(arr) != n:
                raise ValueError(
                    f"Array '{name}' length {len(arr)} != timestamps {n}"
                )

    @property
    def mid_open(self) -> NDArray[np.float64]:
        return (self.bid_open + self.ask_open) / 2.0

    @property
    def mid_high(self) -> NDArray[np.float64]:
        return (self.bid_high + self.ask_high) / 2.0

    @property
    def mid_low(self) -> NDArray[np.float64]:
        return (self.bid_low + self.ask_low) / 2.0

    @property
    def mid_close(self) -> NDArray[np.float64]:
        return (self.bid_close + self.ask_close) / 2.0

    @property
    def spread_open(self) -> NDArray[np.float64]:
        return self.ask_open - self.bid_open

    @property
    def spread_close(self) -> NDArray[np.float64]:
        return self.ask_close - self.bid_close

    def to_mid_series(self) -> BarSeries:
        """Convert to mid-price BarSeries for compatibility."""
        return BarSeries(
            pair=self.pair,
            timeframe=self.timeframe,
            timestamps=self.timestamps,
            open=self.mid_open,
            high=self.mid_high,
            low=self.mid_low,
            close=self.mid_close,
            volume=self.volume,
            spread=self.spread_close,
        )

    def to_bid_series(self) -> BarSeries:
        """Extract bid-side as BarSeries."""
        return BarSeries(
            pair=self.pair,
            timeframe=self.timeframe,
            timestamps=self.timestamps,
            open=self.bid_open,
            high=self.bid_high,
            low=self.bid_low,
            close=self.bid_close,
            volume=self.volume,
        )

    def to_ask_series(self) -> BarSeries:
        """Extract ask-side as BarSeries."""
        return BarSeries(
            pair=self.pair,
            timeframe=self.timeframe,
            timestamps=self.timestamps,
            open=self.ask_open,
            high=self.ask_high,
            low=self.ask_low,
            close=self.ask_close,
            volume=self.volume,
        )

    def slice(self, start: int, end: int) -> BidAskBarSeries:
        """Return a sub-range [start, end)."""
        return BidAskBarSeries(
            pair=self.pair,
            timeframe=self.timeframe,
            timestamps=self.timestamps[start:end],
            bid_open=self.bid_open[start:end],
            bid_high=self.bid_high[start:end],
            bid_low=self.bid_low[start:end],
            bid_close=self.bid_close[start:end],
            ask_open=self.ask_open[start:end],
            ask_high=self.ask_high[start:end],
            ask_low=self.ask_low[start:end],
            ask_close=self.ask_close[start:end],
            volume=self.volume[start:end] if self.volume is not None else None,
            tick_volume=self.tick_volume[start:end] if self.tick_volume is not None else None,
        )

    def validate_invariants(self) -> list[str]:
        """Check bid/ask invariants and return list of violations."""
        violations = []
        n = len(self)

        neg_spread_open = int(np.sum(self.ask_open < self.bid_open))
        if neg_spread_open > 0:
            violations.append(f"Negative spread at open: {neg_spread_open}/{n} bars")

        neg_spread_close = int(np.sum(self.ask_close < self.bid_close))
        if neg_spread_close > 0:
            violations.append(f"Negative spread at close: {neg_spread_close}/{n} bars")

        zero_or_neg_bid = int(np.sum(self.bid_close <= 0))
        if zero_or_neg_bid > 0:
            violations.append(f"Zero/negative bid close: {zero_or_neg_bid}/{n} bars")

        invalid_ohlc_bid = int(np.sum(
            (self.bid_high < self.bid_low) |
            (self.bid_high < self.bid_open) |
            (self.bid_high < self.bid_close) |
            (self.bid_low > self.bid_open) |
            (self.bid_low > self.bid_close)
        ))
        if invalid_ohlc_bid > 0:
            violations.append(f"Invalid bid OHLC: {invalid_ohlc_bid}/{n} bars")

        invalid_ohlc_ask = int(np.sum(
            (self.ask_high < self.ask_low) |
            (self.ask_high < self.ask_open) |
            (self.ask_high < self.ask_close) |
            (self.ask_low > self.ask_open) |
            (self.ask_low > self.ask_close)
        ))
        if invalid_ohlc_ask > 0:
            violations.append(f"Invalid ask OHLC: {invalid_ohlc_ask}/{n} bars")

        return violations
