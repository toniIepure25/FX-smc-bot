"""Yahoo Finance live feed provider for FX candle polling.

Fetches completed H1/H4 candles from Yahoo Finance's free API.
No API key required. Returns only fully completed candles to
avoid partial-bar signals.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from fx_smc_bot.config import Timeframe, TradingPair
from fx_smc_bot.data.providers.live_feed import FeedHealthStatus, FeedStatus
from fx_smc_bot.domain import MarketBar

logger = logging.getLogger(__name__)

_PAIR_TO_YAHOO: dict[TradingPair, str] = {
    TradingPair.EURUSD: "EURUSD=X",
    TradingPair.GBPUSD: "GBPUSD=X",
    TradingPair.USDJPY: "JPY=X",
    TradingPair.GBPJPY: "GBPJPY=X",
}

_TF_TO_YAHOO: dict[Timeframe, str] = {
    Timeframe.M15: "15m",
    Timeframe.H1: "1h",
    Timeframe.H4: "4h",
    Timeframe.D1: "1d",
}


class YahooFeedProvider:
    """Polls Yahoo Finance for completed FX candles.

    Free, no API key, works from any VPS. Uses Yahoo's v8 chart
    endpoint which returns OHLCV data. Only returns bars whose
    close timestamp is in the past (completed bars).
    """

    def __init__(
        self,
        pair: TradingPair,
        timeframe: Timeframe,
        poll_interval_seconds: float = 60.0,
    ) -> None:
        self._pair = pair
        self._timeframe = timeframe
        self._symbol = _PAIR_TO_YAHOO[pair]
        self._interval = _TF_TO_YAHOO[timeframe]
        self._poll_interval = poll_interval_seconds

        self._last_bar_time: datetime | None = None
        self._connected = False
        self._consecutive_errors = 0
        self._last_poll = 0.0
        self._bar_index = 0

    @property
    def pair(self) -> TradingPair:
        return self._pair

    @property
    def timeframe(self) -> Timeframe:
        return self._timeframe

    def poll_new_bars(self, since: datetime | None = None) -> list[MarketBar]:
        now = time.monotonic()
        if now - self._last_poll < self._poll_interval and self._last_poll > 0:
            return []
        self._last_poll = now

        try:
            resp = httpx.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{self._symbol}",
                params={"interval": self._interval, "range": "5d"},
                headers={"User-Agent": "fx-smc-bot/1.0"},
                timeout=15.0,
            )
            resp.raise_for_status()
            data = resp.json()
            self._connected = True
            self._consecutive_errors = 0
        except Exception:
            self._consecutive_errors += 1
            if self._consecutive_errors <= 3:
                logger.warning("Yahoo feed poll failed (attempt %d)", self._consecutive_errors)
            else:
                logger.error("Yahoo feed failing repeatedly (%d)", self._consecutive_errors)
                self._connected = False
            return []

        return self._parse_chart(data, since)

    def _parse_chart(self, data: dict, since: datetime | None) -> list[MarketBar]:
        result = data.get("chart", {}).get("result", [])
        if not result:
            return []

        chart = result[0]
        timestamps = chart.get("timestamp", [])
        indicators = chart.get("indicators", {}).get("quote", [{}])[0]

        opens = indicators.get("open", [])
        highs = indicators.get("high", [])
        lows = indicators.get("low", [])
        closes = indicators.get("close", [])
        volumes = indicators.get("volume", [])

        now_utc = datetime.utcnow()
        bars: list[MarketBar] = []

        for i, ts_epoch in enumerate(timestamps):
            if i >= len(opens) or opens[i] is None or closes[i] is None:
                continue

            ts = datetime.utcfromtimestamp(ts_epoch)

            if self._timeframe == Timeframe.H1:
                bar_end = datetime.utcfromtimestamp(ts_epoch + 3600)
            elif self._timeframe == Timeframe.H4:
                bar_end = datetime.utcfromtimestamp(ts_epoch + 14400)
            else:
                bar_end = datetime.utcfromtimestamp(ts_epoch + 60)

            if bar_end > now_utc:
                continue

            if self._last_bar_time is not None and ts <= self._last_bar_time:
                continue
            if since is not None and ts <= since:
                continue

            bar = MarketBar(
                pair=self._pair,
                timeframe=self._timeframe,
                timestamp=ts,
                open=float(opens[i]),
                high=float(highs[i]),
                low=float(lows[i]),
                close=float(closes[i]),
                bar_index=self._bar_index,
                volume=float(volumes[i]) if volumes and i < len(volumes) and volumes[i] else None,
            )
            bars.append(bar)
            self._bar_index += 1

        if bars:
            self._last_bar_time = bars[-1].timestamp
            logger.info(
                "Yahoo: %d new %s bars for %s (latest: %s)",
                len(bars), self._interval, self._symbol,
                self._last_bar_time.isoformat(),
            )

        return bars

    def fetch_history(self, count: int = 500) -> list[MarketBar]:
        """Fetch historical candles for warmup."""
        range_map = {Timeframe.H1: "60d", Timeframe.H4: "60d", Timeframe.D1: "2y"}
        range_str = range_map.get(self._timeframe, "60d")

        try:
            resp = httpx.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{self._symbol}",
                params={"interval": self._interval, "range": range_str},
                headers={"User-Agent": "fx-smc-bot/1.0"},
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            self._connected = True
        except Exception:
            logger.exception("Yahoo history fetch failed")
            return []

        bars = self._parse_chart(data, since=None)
        if bars and count < len(bars):
            bars = bars[-count:]
        if bars:
            self._last_bar_time = bars[-1].timestamp
            self._bar_index = len(bars)
            logger.info("Yahoo history: %d bars (from %s to %s)",
                        len(bars), bars[0].timestamp, bars[-1].timestamp)
        return bars

    def heartbeat(self) -> FeedHealthStatus:
        if not self._connected and self._consecutive_errors > 0:
            return FeedHealthStatus(
                status=FeedStatus.ERROR,
                last_bar_time=self._last_bar_time,
                message=f"Yahoo errors: {self._consecutive_errors}",
            )
        if self._connected:
            return FeedHealthStatus(
                status=FeedStatus.CONNECTED,
                last_bar_time=self._last_bar_time,
                message=f"Yahoo {self._symbol} {self._interval}",
            )
        return FeedHealthStatus(
            status=FeedStatus.DISCONNECTED,
            last_bar_time=self._last_bar_time,
            message="Yahoo: not yet polled",
        )

    def is_connected(self) -> bool:
        return self._connected
