"""OANDA v20 REST API feed provider for live H1/H4 candle polling.

Polls the OANDA instruments endpoint for completed candles and converts
them to MarketBar objects. Supports both practice and live environments.

Requires:
  - OANDA_API_KEY environment variable (or passed directly)
  - OANDA_ACCOUNT_ID environment variable (or passed directly)

Practice API: https://api-fxpractice.oanda.com
Live API:     https://api-fxtrade.oanda.com
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

_PAIR_TO_OANDA: dict[TradingPair, str] = {
    TradingPair.EURUSD: "EUR_USD",
    TradingPair.GBPUSD: "GBP_USD",
    TradingPair.USDJPY: "USD_JPY",
    TradingPair.GBPJPY: "GBP_JPY",
}

_TF_TO_OANDA: dict[Timeframe, str] = {
    Timeframe.M1: "M1",
    Timeframe.M5: "M5",
    Timeframe.M15: "M15",
    Timeframe.H1: "H1",
    Timeframe.H4: "H4",
    Timeframe.D1: "D",
}


class OandaFeedProvider:
    """Polls OANDA REST API for completed candles.

    Works with both practice and live accounts. Only returns fully
    completed candles (complete=true) to avoid partial bar signals.
    """

    def __init__(
        self,
        pair: TradingPair,
        timeframe: Timeframe,
        api_key: str,
        account_id: str,
        practice: bool = True,
        poll_interval_seconds: float = 30.0,
    ) -> None:
        self._pair = pair
        self._timeframe = timeframe
        self._instrument = _PAIR_TO_OANDA[pair]
        self._granularity = _TF_TO_OANDA[timeframe]
        self._account_id = account_id
        self._poll_interval = poll_interval_seconds

        base = "https://api-fxpractice.oanda.com" if practice else "https://api-fxtrade.oanda.com"
        self._candles_url = f"{base}/v3/instruments/{self._instrument}/candles"
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

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

        params: dict[str, Any] = {
            "granularity": self._granularity,
            "price": "M",
            "count": 5,
        }
        if since is not None:
            from_str = since.replace(tzinfo=timezone.utc).isoformat()
            params["from"] = from_str
            params.pop("count", None)

        try:
            resp = httpx.get(
                self._candles_url,
                headers=self._headers,
                params=params,
                timeout=15.0,
            )
            resp.raise_for_status()
            data = resp.json()
            self._connected = True
            self._consecutive_errors = 0
        except Exception:
            self._consecutive_errors += 1
            if self._consecutive_errors <= 3:
                logger.warning("OANDA poll failed (attempt %d)", self._consecutive_errors)
            else:
                logger.error("OANDA poll failing repeatedly (%d)", self._consecutive_errors)
                self._connected = False
            return []

        candles = data.get("candles", [])
        bars: list[MarketBar] = []

        for c in candles:
            if not c.get("complete", False):
                continue

            mid = c.get("mid", {})
            ts_str = c.get("time", "")
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).replace(tzinfo=None)
            except (ValueError, AttributeError):
                continue

            if self._last_bar_time is not None and ts <= self._last_bar_time:
                continue

            bar = MarketBar(
                pair=self._pair,
                timeframe=self._timeframe,
                timestamp=ts,
                open=float(mid.get("o", 0)),
                high=float(mid.get("h", 0)),
                low=float(mid.get("l", 0)),
                close=float(mid.get("c", 0)),
                bar_index=self._bar_index,
                volume=float(c.get("volume", 0)),
            )
            bars.append(bar)
            self._bar_index += 1

        if bars:
            self._last_bar_time = bars[-1].timestamp
            logger.info(
                "OANDA: %d new %s bars for %s (latest: %s)",
                len(bars), self._granularity, self._instrument,
                self._last_bar_time.isoformat(),
            )

        return bars

    def heartbeat(self) -> FeedHealthStatus:
        if not self._connected and self._consecutive_errors > 0:
            return FeedHealthStatus(
                status=FeedStatus.ERROR,
                last_bar_time=self._last_bar_time,
                message=f"OANDA errors: {self._consecutive_errors}",
            )
        if self._connected:
            return FeedHealthStatus(
                status=FeedStatus.CONNECTED,
                last_bar_time=self._last_bar_time,
                message=f"OANDA {self._instrument} {self._granularity}",
            )
        return FeedHealthStatus(
            status=FeedStatus.DISCONNECTED,
            last_bar_time=self._last_bar_time,
            message="OANDA: not yet polled",
        )

    def is_connected(self) -> bool:
        return self._connected

    def fetch_history(self, count: int = 500) -> list[MarketBar]:
        """Fetch historical candles for warmup. Returns completed bars only."""
        params = {
            "granularity": self._granularity,
            "price": "M",
            "count": min(count, 5000),
        }

        try:
            resp = httpx.get(
                self._candles_url,
                headers=self._headers,
                params=params,
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            logger.exception("OANDA history fetch failed")
            return []

        bars: list[MarketBar] = []
        for i, c in enumerate(data.get("candles", [])):
            if not c.get("complete", False):
                continue
            mid = c.get("mid", {})
            ts_str = c.get("time", "")
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).replace(tzinfo=None)
            except (ValueError, AttributeError):
                continue
            bars.append(MarketBar(
                pair=self._pair,
                timeframe=self._timeframe,
                timestamp=ts,
                open=float(mid.get("o", 0)),
                high=float(mid.get("h", 0)),
                low=float(mid.get("l", 0)),
                close=float(mid.get("c", 0)),
                bar_index=i,
                volume=float(c.get("volume", 0)),
            ))

        if bars:
            self._last_bar_time = bars[-1].timestamp
            self._bar_index = len(bars)
            self._connected = True
            logger.info("OANDA history: %d bars loaded (from %s to %s)",
                        len(bars), bars[0].timestamp, bars[-1].timestamp)

        return bars
