from dataclasses import replace
from datetime import datetime

import numpy as np

from fx_smc_bot.alpha.intraday.runtime import CausalBarContext, OrderIntent
from fx_smc_bot.config import Timeframe, TradingPair
from fx_smc_bot.data.bidask import BidAskBarSeries
from fx_smc_bot.domain import Direction, StructureSnapshot
from fx_smc_bot.research.quant_polarity_execution import (
    _trade_outcome,
    extract_signal_features,
    invert_runtime_intent,
)


def _intent() -> OrderIntent:
    return OrderIntent(
        family="opening_range_displacement_fvg_retest",
        pair=TradingPair.AUDUSD,
        direction=Direction.LONG,
        entry_price=0.7,
        stop_loss=0.699,
        take_profit=0.702,
        signal_timestamp=datetime(2019, 1, 2, 9),
        session="london",
    )


def test_runtime_inversion_preserves_distances_and_timestamps() -> None:
    original = _intent()
    inverse = invert_runtime_intent(original)
    assert inverse.direction is Direction.SHORT
    assert inverse.signal_timestamp == original.signal_timestamp
    assert inverse.entry_price == original.entry_price
    assert inverse.stop_loss - inverse.entry_price == original.entry_price - original.stop_loss
    assert inverse.entry_price - inverse.take_profit == original.take_profit - original.entry_price


def test_future_bar_perturbation_leaves_features_unchanged() -> None:
    count = 400
    decision_index = 320
    timestamps = np.datetime64("2019-01-01T00:00") + np.arange(count) * np.timedelta64(5, "m")
    close = 0.7 + np.arange(count) * 0.00001
    high = close + 0.0001
    low = close - 0.0001
    open_ = close - 0.00001
    spread = np.full(count, 0.0001)
    series = BidAskBarSeries(
        pair=TradingPair.AUDUSD,
        timeframe=Timeframe.M5,
        timestamps=timestamps,
        bid_open=open_ - spread / 2,
        bid_high=high - spread / 2,
        bid_low=low - spread / 2,
        bid_close=close - spread / 2,
        ask_open=open_ + spread / 2,
        ask_high=high + spread / 2,
        ask_low=low + spread / 2,
        ask_close=close + spread / 2,
    )
    ctx = CausalBarContext(
        pair=TradingPair.AUDUSD,
        timeframe=Timeframe.M5,
        bar_idx=decision_index,
        timestamp=timestamps[decision_index].astype("datetime64[us]").astype(datetime),
        open=open_,
        high=high,
        low=low,
        close=close,
        atr=0.001,
        spread=0.0001,
        snapshot=StructureSnapshot(TradingPair.AUDUSD, Timeframe.M5, decision_index),
    )
    original = extract_signal_features(ctx, series, _intent())
    changed_close = close.copy()
    changed_close[decision_index + 1 :] += 1.0
    changed_series = replace(
        series,
        bid_close=changed_close - spread / 2,
        ask_close=changed_close + spread / 2,
    )
    changed_ctx = replace(ctx, close=changed_close)
    assert extract_signal_features(changed_ctx, changed_series, _intent()) == original


def test_cost_stress_scales_spread_and_slippage_but_not_commission() -> None:
    class TwoBarSeries:
        bid_close = np.asarray([1.1000, 1.1010])
        ask_close = np.asarray([1.1002, 1.1014])

        def __len__(self) -> int:
            return 2

    class Trade:
        initial_risk_cash = 100.0
        entry_bar = 0
        exit_bar = 1
        units = 100_000.0
        entry_slippage_price = 0.00001
        exit_slippage_price = 0.00001
        commission_cost = 10.0
        net_pnl = 80.0
        entry_time = None
        exit_time = None
        exit_reason = "test"
        direction = "long"

    outcome = _trade_outcome(Trade(), TwoBarSeries())
    assert outcome["commission_cash"] == 10.0
    assert np.isclose(outcome["spread_cash"], 30.0)
    assert np.isclose(outcome["slippage_cash"], 2.0)
    assert np.isclose(outcome["gross_r"], 1.22)
    assert np.isclose(outcome["net_r"], 0.8)
    assert np.isclose(outcome["stress_1_5x_net_r"], 0.64)
    assert np.isclose(outcome["stress_2_0x_net_r"], 0.48)
