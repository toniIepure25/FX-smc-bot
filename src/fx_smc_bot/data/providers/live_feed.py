"""Live feed provider protocol and concrete implementations.

LiveFeedProvider defines a pull-based interface for incremental bar ingestion
suitable for forward paper validation and eventual broker-feed integration.

Implementations:
    ReplayFeedProvider  — wraps a static BarSeries to simulate live arrival
    FileWatchFeedProvider — monitors a directory for new CSV/Parquet appends
    PollingFeedProvider  — stub for HTTP/API polling (future broker feeds)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np

from fx_smc_bot.config import Timeframe, TradingPair
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.domain import MarketBar

logger = logging.getLogger(__name__)


class FeedStatus(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    STALE = "stale"
    ERROR = "error"


@dataclass(slots=True, frozen=True)
class FeedHealthStatus:
    status: FeedStatus
    last_bar_time: datetime | None
    latency_ms: float = 0.0
    message: str = ""


@runtime_checkable
class LiveFeedProvider(Protocol):
    """Pull-based interface for live bar ingestion."""

    def poll_new_bars(self, since: datetime | None = None) -> list[MarketBar]:
        """Return bars newer than *since* (or all available if None)."""
        ...

    def heartbeat(self) -> FeedHealthStatus:
        """Return current feed health."""
        ...

    def is_connected(self) -> bool: ...

    @property
    def pair(self) -> TradingPair: ...

    @property
    def timeframe(self) -> Timeframe: ...


class ReplayFeedProvider:
    """Wraps a static BarSeries to simulate live bar arrival.

    Each call to ``poll_new_bars`` advances by one bar, making it suitable
    for testing the ForwardPaperRunner without a live data source.
    """

    def __init__(
        self,
        series: BarSeries,
        speed_factor: float = 0.0,
    ) -> None:
        self._series = series
        self._bars = series.to_bars()
        self._cursor = 0
        self._speed_factor = speed_factor
        self._last_poll: float = time.monotonic()

    @property
    def pair(self) -> TradingPair:
        return self._series.pair

    @property
    def timeframe(self) -> Timeframe:
        return self._series.timeframe

    def poll_new_bars(self, since: datetime | None = None) -> list[MarketBar]:
        if self._cursor >= len(self._bars):
            return []

        if since is not None:
            while self._cursor < len(self._bars) and self._bars[self._cursor].timestamp <= since:
                self._cursor += 1
            if self._cursor >= len(self._bars):
                return []

        if self._speed_factor > 0:
            elapsed = time.monotonic() - self._last_poll
            wait = self._speed_factor - elapsed
            if wait > 0:
                time.sleep(wait)

        bar = self._bars[self._cursor]
        self._cursor += 1
        self._last_poll = time.monotonic()
        return [bar]

    def heartbeat(self) -> FeedHealthStatus:
        if self._cursor >= len(self._bars):
            return FeedHealthStatus(
                status=FeedStatus.DISCONNECTED,
                last_bar_time=self._bars[-1].timestamp if self._bars else None,
                message="replay_exhausted",
            )
        return FeedHealthStatus(
            status=FeedStatus.CONNECTED,
            last_bar_time=self._bars[self._cursor - 1].timestamp if self._cursor > 0 else None,
            message=f"replay: {self._cursor}/{len(self._bars)}",
        )

    def is_connected(self) -> bool:
        return self._cursor < len(self._bars)

    @property
    def remaining(self) -> int:
        return max(0, len(self._bars) - self._cursor)


class FileWatchFeedProvider:
    """Monitors a directory for new CSV/Parquet bar data files.

    Suitable for paper validation with delayed feeds or manual data drops.
    Files are expected to contain bars for a single pair/timeframe and to
    be named with a sortable timestamp prefix.
    """

    def __init__(
        self,
        watch_dir: Path | str,
        pair: TradingPair,
        timeframe: Timeframe,
        file_pattern: str = "*.csv",
    ) -> None:
        self._watch_dir = Path(watch_dir)
        self._pair = pair
        self._timeframe = timeframe
        self._file_pattern = file_pattern
        self._processed_files: set[str] = set()
        self._last_bar_time: datetime | None = None

    @property
    def pair(self) -> TradingPair:
        return self._pair

    @property
    def timeframe(self) -> Timeframe:
        return self._timeframe

    def poll_new_bars(self, since: datetime | None = None) -> list[MarketBar]:
        if not self._watch_dir.exists():
            return []

        new_files = sorted(
            f for f in self._watch_dir.glob(self._file_pattern)
            if f.name not in self._processed_files
        )

        bars: list[MarketBar] = []
        for filepath in new_files:
            try:
                file_bars = self._load_file(filepath)
                if since is not None:
                    file_bars = [b for b in file_bars if b.timestamp > since]
                bars.extend(file_bars)
                self._processed_files.add(filepath.name)
            except Exception:
                logger.exception("Failed to load feed file: %s", filepath)

        if bars:
            bars.sort(key=lambda b: b.timestamp)
            self._last_bar_time = bars[-1].timestamp

        return bars

    def _load_file(self, filepath: Path) -> list[MarketBar]:
        """Load bars from CSV. Expects columns: timestamp,open,high,low,close[,volume][,spread]."""
        import csv
        bars: list[MarketBar] = []
        with open(filepath) as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader):
                ts = datetime.fromisoformat(row["timestamp"])
                bars.append(MarketBar(
                    pair=self._pair,
                    timeframe=self._timeframe,
                    timestamp=ts,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    bar_index=i,
                    volume=float(row["volume"]) if "volume" in row and row["volume"] else None,
                    spread=float(row["spread"]) if "spread" in row and row["spread"] else None,
                ))
        return bars

    def heartbeat(self) -> FeedHealthStatus:
        if not self._watch_dir.exists():
            return FeedHealthStatus(
                status=FeedStatus.ERROR,
                last_bar_time=self._last_bar_time,
                message=f"watch_dir not found: {self._watch_dir}",
            )
        return FeedHealthStatus(
            status=FeedStatus.CONNECTED,
            last_bar_time=self._last_bar_time,
            message=f"watching: {self._watch_dir}",
        )

    def is_connected(self) -> bool:
        return self._watch_dir.exists()


class PollingFeedProvider:
    """Stub for HTTP/API-based feed polling.

    Designed for future integration with broker REST APIs or market data
    services. The ``fetch_url`` and response parsing must be implemented
    for the specific data source.
    """

    def __init__(
        self,
        pair: TradingPair,
        timeframe: Timeframe,
        endpoint_url: str = "",
        poll_interval_seconds: float = 60.0,
    ) -> None:
        self._pair = pair
        self._timeframe = timeframe
        self._endpoint_url = endpoint_url
        self._poll_interval = poll_interval_seconds
        self._last_bar_time: datetime | None = None
        self._connected = False

    @property
    def pair(self) -> TradingPair:
        return self._pair

    @property
    def timeframe(self) -> Timeframe:
        return self._timeframe

    def poll_new_bars(self, since: datetime | None = None) -> list[MarketBar]:
        if not self._endpoint_url:
            logger.warning("PollingFeedProvider: no endpoint configured")
            return []
        # Future implementation: httpx.get(self._endpoint_url, params=...)
        # Parse response into MarketBar list, filter by `since`
        logger.info("PollingFeedProvider.poll_new_bars: stub — no implementation yet")
        return []

    def heartbeat(self) -> FeedHealthStatus:
        if not self._endpoint_url:
            return FeedHealthStatus(
                status=FeedStatus.DISCONNECTED,
                last_bar_time=self._last_bar_time,
                message="no endpoint configured",
            )
        return FeedHealthStatus(
            status=FeedStatus.CONNECTED if self._connected else FeedStatus.DISCONNECTED,
            last_bar_time=self._last_bar_time,
            message=f"endpoint: {self._endpoint_url}",
        )

    def is_connected(self) -> bool:
        return self._connected
