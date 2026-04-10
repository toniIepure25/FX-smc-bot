"""Shared test helpers: synthetic data builders for backtest engine tests."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from fx_smc_bot.config import Timeframe, TradingPair
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.domain import MarketBar


def make_synthetic_data(
    pairs: list[TradingPair] | None = None,
    n_bars: int = 200,
    timeframe: Timeframe = Timeframe.M15,
    seed: int = 42,
) -> dict[TradingPair, BarSeries]:
    """Generate synthetic BarSeries data suitable for engine tests."""
    if pairs is None:
        pairs = [TradingPair.EURUSD]

    rng = np.random.default_rng(seed)
    start = datetime(2024, 1, 2, 0, 0)
    delta = timedelta(minutes=15)

    result: dict[TradingPair, BarSeries] = {}
    for pair in pairs:
        base = 1.1000 if "JPY" not in pair.value else 150.0
        vol = 0.0010 if "JPY" not in pair.value else 0.10

        bars: list[MarketBar] = []
        price = base
        for i in range(n_bars):
            ts = start + delta * i
            open_ = price
            move = rng.normal(0.0, vol)
            close = open_ + move
            high = max(open_, close) + abs(rng.normal(0, vol * 0.5))
            low = min(open_, close) - abs(rng.normal(0, vol * 0.5))
            bars.append(MarketBar(
                pair=pair, timeframe=timeframe, timestamp=ts,
                open=round(open_, 5), high=round(high, 5),
                low=round(low, 5), close=round(close, 5),
                bar_index=i, spread=round(vol * 0.15, 6),
            ))
            price = close

        result[pair] = BarSeries.from_bars(bars)

    return result
