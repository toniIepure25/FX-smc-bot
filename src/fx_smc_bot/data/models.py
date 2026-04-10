"""BarSeries: typed wrapper around aligned numpy arrays for OHLCV data.

BarSeries is the central data contract between the data layer and all
downstream consumers (structure engine, alpha, backtesting).  It stores
columnar numpy arrays and provides typed accessors, avoiding repeated
DataFrame conversions in hot loops.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
from numpy.typing import NDArray

from fx_smc_bot.config import Timeframe, TradingPair
from fx_smc_bot.domain import MarketBar


@dataclass(slots=True)
class BarSeries:
    """Columnar representation of a sequence of market bars for one pair/timeframe."""

    pair: TradingPair
    timeframe: Timeframe
    timestamps: NDArray[np.datetime64]
    open: NDArray[np.float64]
    high: NDArray[np.float64]
    low: NDArray[np.float64]
    close: NDArray[np.float64]
    volume: NDArray[np.float64] | None = None
    spread: NDArray[np.float64] | None = None

    def __len__(self) -> int:
        return len(self.timestamps)

    def __post_init__(self) -> None:
        n = len(self.timestamps)
        for name in ("open", "high", "low", "close"):
            arr = getattr(self, name)
            if len(arr) != n:
                raise ValueError(f"Array '{name}' length {len(arr)} != timestamps length {n}")

    @classmethod
    def from_bars(cls, bars: list[MarketBar]) -> BarSeries:
        """Construct from a list of MarketBar domain objects."""
        if not bars:
            raise ValueError("Cannot create BarSeries from empty list")
        pair = bars[0].pair
        tf = bars[0].timeframe
        n = len(bars)
        ts = np.array([np.datetime64(b.timestamp) for b in bars], dtype="datetime64[ns]")
        o = np.array([b.open for b in bars], dtype=np.float64)
        h = np.array([b.high for b in bars], dtype=np.float64)
        lo = np.array([b.low for b in bars], dtype=np.float64)
        c = np.array([b.close for b in bars], dtype=np.float64)
        vol = np.array([b.volume if b.volume is not None else 0.0 for b in bars], dtype=np.float64)
        sp = np.array([b.spread if b.spread is not None else np.nan for b in bars], dtype=np.float64)
        has_vol = any(b.volume is not None for b in bars)
        has_sp = any(b.spread is not None for b in bars)
        return cls(
            pair=pair, timeframe=tf, timestamps=ts,
            open=o, high=h, low=lo, close=c,
            volume=vol if has_vol else None,
            spread=sp if has_sp else None,
        )

    def to_bars(self) -> list[MarketBar]:
        """Convert back to a list of MarketBar objects."""
        bars: list[MarketBar] = []
        for i in range(len(self)):
            ts_dt = self.timestamps[i].astype("datetime64[us]").astype(datetime)
            bars.append(MarketBar(
                pair=self.pair, timeframe=self.timeframe,
                timestamp=ts_dt,
                open=float(self.open[i]), high=float(self.high[i]),
                low=float(self.low[i]), close=float(self.close[i]),
                bar_index=i,
                volume=float(self.volume[i]) if self.volume is not None else None,
                spread=float(self.spread[i]) if self.spread is not None else None,
            ))
        return bars

    def slice(self, start: int, end: int) -> BarSeries:
        """Return a sub-range [start, end)."""
        return BarSeries(
            pair=self.pair, timeframe=self.timeframe,
            timestamps=self.timestamps[start:end],
            open=self.open[start:end], high=self.high[start:end],
            low=self.low[start:end], close=self.close[start:end],
            volume=self.volume[start:end] if self.volume is not None else None,
            spread=self.spread[start:end] if self.spread is not None else None,
        )
