"""Shared test fixtures: synthetic market bars, configs, etc."""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import numpy as np
import pytest

from fx_smc_bot.config import AppConfig, Timeframe, TradingPair
from fx_smc_bot.domain import MarketBar


@pytest.fixture()
def default_config() -> AppConfig:
    return AppConfig()


def make_bars(
    n: int = 100,
    pair: TradingPair = TradingPair.EURUSD,
    timeframe: Timeframe = Timeframe.M15,
    start: datetime | None = None,
    base_price: float = 1.1000,
    volatility: float = 0.0010,
    trend: float = 0.0,
    seed: int = 42,
) -> list[MarketBar]:
    """Generate synthetic OHLC bars with controllable trend and volatility.

    Produces realistic-ish candle shapes: open derived from prior close,
    high/low extend from open, close sits within range.
    """
    rng = np.random.default_rng(seed)
    start = start or datetime(2024, 1, 2, 0, 0)
    minutes = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
    delta = timedelta(minutes=minutes.get(timeframe.value, 15))

    bars: list[MarketBar] = []
    price = base_price
    for i in range(n):
        ts = start + delta * i
        open_ = price
        move = rng.normal(trend, volatility)
        close = open_ + move
        high = max(open_, close) + abs(rng.normal(0, volatility * 0.5))
        low = min(open_, close) - abs(rng.normal(0, volatility * 0.5))
        bars.append(MarketBar(
            pair=pair,
            timeframe=timeframe,
            timestamp=ts,
            open=round(open_, 5),
            high=round(high, 5),
            low=round(low, 5),
            close=round(close, 5),
            bar_index=i,
            spread=0.00015,
        ))
        price = close
    return bars


def make_trending_bars(
    n: int = 60,
    direction: str = "up",
    pair: TradingPair = TradingPair.EURUSD,
    timeframe: Timeframe = Timeframe.M15,
    start: datetime | None = None,
    base_price: float = 1.1000,
    seed: int = 42,
) -> list[MarketBar]:
    """Generate bars with a clear trend for structure detection tests."""
    trend = 0.0003 if direction == "up" else -0.0003
    return make_bars(
        n=n, pair=pair, timeframe=timeframe, start=start,
        base_price=base_price, volatility=0.0008, trend=trend, seed=seed,
    )


def make_swing_pattern_bars(
    pair: TradingPair = TradingPair.EURUSD,
    timeframe: Timeframe = Timeframe.M15,
) -> list[MarketBar]:
    """Generate bars with known swing highs and lows for deterministic testing.

    Pattern: rise to 1.1050, drop to 1.0950, rise to 1.1080, drop to 1.0920.
    This guarantees at least two swing highs and two swing lows.
    """
    prices = [
        # Rise phase 1
        1.1000, 1.1010, 1.1020, 1.1030, 1.1040, 1.1050,
        # Drop phase 1
        1.1040, 1.1020, 1.1000, 1.0980, 1.0960, 1.0950,
        # Rise phase 2 (higher high)
        1.0960, 1.0980, 1.1010, 1.1040, 1.1060, 1.1080,
        # Drop phase 2 (lower low)
        1.1060, 1.1030, 1.1000, 1.0960, 1.0940, 1.0920,
        # Rise phase 3
        1.0940, 1.0960, 1.0990, 1.1010, 1.1030,
    ]

    start = datetime(2024, 1, 2, 8, 0)
    delta = timedelta(minutes=15)
    bars: list[MarketBar] = []
    for i, p in enumerate(prices):
        spread = 0.0010
        bars.append(MarketBar(
            pair=pair,
            timeframe=timeframe,
            timestamp=start + delta * i,
            open=round(p - 0.0002, 5),
            high=round(p + spread / 2, 5),
            low=round(p - spread / 2, 5),
            close=round(p, 5),
            bar_index=i,
            spread=0.00015,
        ))
    return bars
