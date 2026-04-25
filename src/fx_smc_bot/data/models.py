"""BarSeries: typed wrapper around aligned numpy arrays for OHLCV data.

BarSeries is the central data contract between the data layer and all
downstream consumers (structure engine, alpha, backtesting).  It stores
columnar numpy arrays and provides typed accessors, avoiding repeated
DataFrame conversions in hot loops.

BarBuffer provides a fixed-capacity ring buffer for live bar accumulation
that produces BarSeries snapshots without copying the entire history.
"""

from __future__ import annotations

import threading
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


class BarBuffer:
    """Fixed-capacity ring buffer for live bar accumulation.

    Thread-safe append + snapshot: a feed thread can append bars while the
    strategy thread reads consistent ``BarSeries`` snapshots.
    """

    def __init__(
        self,
        pair: TradingPair,
        timeframe: Timeframe,
        capacity: int = 2000,
    ) -> None:
        self._pair = pair
        self._timeframe = timeframe
        self._capacity = capacity
        self._lock = threading.Lock()

        self._timestamps = np.empty(capacity, dtype="datetime64[ns]")
        self._open = np.empty(capacity, dtype=np.float64)
        self._high = np.empty(capacity, dtype=np.float64)
        self._low = np.empty(capacity, dtype=np.float64)
        self._close = np.empty(capacity, dtype=np.float64)
        self._volume = np.empty(capacity, dtype=np.float64)
        self._spread = np.empty(capacity, dtype=np.float64)

        self._size = 0
        self._head = 0  # next write position

    @property
    def pair(self) -> TradingPair:
        return self._pair

    @property
    def timeframe(self) -> Timeframe:
        return self._timeframe

    def __len__(self) -> int:
        with self._lock:
            return self._size

    @property
    def capacity(self) -> int:
        return self._capacity

    def append(
        self,
        timestamp: datetime,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: float = 0.0,
        spread: float = 0.0,
    ) -> None:
        """Append a single bar. Evicts the oldest bar when at capacity."""
        with self._lock:
            pos = self._head
            self._timestamps[pos] = np.datetime64(timestamp, "ns")
            self._open[pos] = open_
            self._high[pos] = high
            self._low[pos] = low
            self._close[pos] = close
            self._volume[pos] = volume
            self._spread[pos] = spread

            self._head = (pos + 1) % self._capacity
            if self._size < self._capacity:
                self._size += 1

    def append_bar(self, bar: MarketBar) -> None:
        """Append from a ``MarketBar`` domain object."""
        self.append(
            bar.timestamp, bar.open, bar.high, bar.low, bar.close,
            bar.volume or 0.0, bar.spread or 0.0,
        )

    def to_series(self) -> BarSeries:
        """Return an immutable ``BarSeries`` snapshot of the buffered bars.

        The returned arrays are contiguous copies ordered oldest-first.
        """
        with self._lock:
            if self._size == 0:
                raise ValueError("BarBuffer is empty — cannot create BarSeries")
            if self._size < self._capacity:
                sl = slice(0, self._size)
                ts = self._timestamps[sl].copy()
                o = self._open[sl].copy()
                h = self._high[sl].copy()
                lo = self._low[sl].copy()
                c = self._close[sl].copy()
                v = self._volume[sl].copy()
                sp = self._spread[sl].copy()
            else:
                # Wrapped ring — stitch tail + head portions
                start = self._head  # oldest element
                ts = np.concatenate([self._timestamps[start:], self._timestamps[:start]])
                o = np.concatenate([self._open[start:], self._open[:start]])
                h = np.concatenate([self._high[start:], self._high[:start]])
                lo = np.concatenate([self._low[start:], self._low[:start]])
                c = np.concatenate([self._close[start:], self._close[:start]])
                v = np.concatenate([self._volume[start:], self._volume[:start]])
                sp = np.concatenate([self._spread[start:], self._spread[:start]])

        return BarSeries(
            pair=self._pair,
            timeframe=self._timeframe,
            timestamps=ts,
            open=o,
            high=h,
            low=lo,
            close=c,
            volume=v,
            spread=sp,
        )

    @property
    def last_timestamp(self) -> datetime | None:
        """Timestamp of the most recently appended bar, or ``None``."""
        with self._lock:
            if self._size == 0:
                return None
            last_pos = (self._head - 1) % self._capacity
            return self._timestamps[last_pos].astype("datetime64[us]").astype(datetime)

    def clear(self) -> None:
        with self._lock:
            self._size = 0
            self._head = 0
