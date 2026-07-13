"""Shared test helpers for Gate C.2 end-to-end tests."""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
from numpy.typing import NDArray

from fx_smc_bot.config import PAIR_PIP_INFO, Timeframe, TradingPair
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.data.bidask import BidAskBarSeries
from fx_smc_bot.domain import (
    Direction,
    FVGZone,
    LiquidityLevel,
    LiquidityLevelType,
    StructureSnapshot,
    SwingPoint,
    SwingType,
)


def make_bar_series(
    pair: TradingPair = TradingPair.EURUSD,
    timeframe: Timeframe = Timeframe.M5,
    n: int = 100,
    base_price: float = 1.1000,
    start: datetime | None = None,
    seed: int = 42,
) -> BarSeries:
    """Create a deterministic synthetic BarSeries."""
    rng = np.random.default_rng(seed)
    if start is None:
        start = datetime(2023, 6, 15, 8, 0, 0)

    tf_minutes = {Timeframe.M1: 1, Timeframe.M5: 5, Timeframe.M15: 15, Timeframe.H1: 60}
    delta = timedelta(minutes=tf_minutes.get(timeframe, 5))

    timestamps = np.array(
        [np.datetime64(start + delta * i) for i in range(n)],
        dtype="datetime64[ns]",
    )

    pip_size = PAIR_PIP_INFO.get(pair, (0.0001, 4))[0]
    step = pip_size * 5

    close = np.zeros(n, dtype=np.float64)
    close[0] = base_price
    for i in range(1, n):
        close[i] = close[i - 1] + rng.normal(0, step)

    open_ = np.zeros(n, dtype=np.float64)
    open_[0] = base_price
    for i in range(1, n):
        open_[i] = close[i - 1] + rng.normal(0, step * 0.2)

    high = np.maximum(open_, close) + rng.uniform(0, step * 2, n)
    low = np.minimum(open_, close) - rng.uniform(0, step * 2, n)

    spread = np.full(n, pip_size * 1.5, dtype=np.float64)

    return BarSeries(
        pair=pair,
        timeframe=timeframe,
        timestamps=timestamps,
        open=open_,
        high=high,
        low=low,
        close=close,
        spread=spread,
    )


def make_bidask_series(
    pair: TradingPair = TradingPair.EURUSD,
    timeframe: Timeframe = Timeframe.M5,
    n: int = 100,
    base_price: float = 1.1000,
    spread_pips: float = 1.5,
    start: datetime | None = None,
    seed: int = 42,
) -> BidAskBarSeries:
    """Create a deterministic synthetic BidAskBarSeries."""
    mid = make_bar_series(pair, timeframe, n, base_price, start, seed)
    pip_size = PAIR_PIP_INFO.get(pair, (0.0001, 4))[0]
    half_spread = spread_pips * pip_size / 2

    return BidAskBarSeries(
        pair=pair,
        timeframe=timeframe,
        timestamps=mid.timestamps,
        bid_open=mid.open - half_spread,
        bid_high=mid.high - half_spread,
        bid_low=mid.low - half_spread,
        bid_close=mid.close - half_spread,
        ask_open=mid.open + half_spread,
        ask_high=mid.high + half_spread,
        ask_low=mid.low + half_spread,
        ask_close=mid.close + half_spread,
    )


def make_sweep_setup_series(
    pair: TradingPair = TradingPair.EURUSD,
    start: datetime | None = None,
) -> tuple[BarSeries, LiquidityLevel]:
    """Create a bar series that produces a liquidity sweep scenario.

    Returns (series, level) where the level is swept at a known bar.
    """
    if start is None:
        start = datetime(2023, 6, 15, 8, 0, 0)

    pip = PAIR_PIP_INFO.get(pair, (0.0001, 4))[0]
    n = 80
    delta = timedelta(minutes=5)

    timestamps = np.array(
        [np.datetime64(start + delta * i) for i in range(n)],
        dtype="datetime64[ns]",
    )

    base = 1.1000 if pair in (TradingPair.EURUSD, TradingPair.GBPUSD) else 140.00

    open_ = np.full(n, base, dtype=np.float64)
    high = np.full(n, base + 10 * pip, dtype=np.float64)
    low = np.full(n, base - 10 * pip, dtype=np.float64)
    close = np.full(n, base, dtype=np.float64)

    level_price = base + 15 * pip
    level = LiquidityLevel(
        price=level_price,
        level_type=LiquidityLevelType.SESSION_HIGH,
        touch_count=2,
        formation_index=5,
        formation_time=start + delta * 5,
    )

    sweep_bar = 35
    high[sweep_bar] = level_price + 5 * pip
    close[sweep_bar] = level_price + 3 * pip
    open_[sweep_bar] = base + 12 * pip

    reclaim_bar = 37
    close[reclaim_bar] = level_price - 2 * pip
    open_[reclaim_bar] = level_price + 1 * pip
    high[reclaim_bar] = level_price + 1 * pip
    low[reclaim_bar] = level_price - 3 * pip

    for i in range(reclaim_bar + 1, reclaim_bar + 5):
        if i >= n:
            break
        close[i] = level_price - (3 + i - reclaim_bar) * pip
        open_[i] = close[i] + pip
        high[i] = open_[i] + 2 * pip
        low[i] = close[i] - pip

    disp_bar = reclaim_bar + 3
    if disp_bar < n:
        body = 30 * pip
        open_[disp_bar] = close[disp_bar - 1]
        close[disp_bar] = open_[disp_bar] - body
        high[disp_bar] = open_[disp_bar] + pip
        low[disp_bar] = close[disp_bar] - pip

    spread = np.full(n, pip * 1.5, dtype=np.float64)

    series = BarSeries(
        pair=pair,
        timeframe=Timeframe.M5,
        timestamps=timestamps,
        open=open_, high=high, low=low, close=close,
        spread=spread,
    )

    return series, level
