from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from fx_smc_bot.alpha.intraday.factory import resolve_runtime_config
from fx_smc_bot.alpha.intraday.runtime import CausalBarContext, OrderIntent
from fx_smc_bot.backtesting.intraday_engine import (
    IntradayBacktestEngine,
    IntradayExecutionPolicy,
)
from fx_smc_bot.config import (
    AppConfig,
    BacktestConfig,
    ExecutionConfig,
    Timeframe,
    TradingPair,
)
from fx_smc_bot.data.bidask import BidAskBarSeries
from fx_smc_bot.domain import Direction, StructureSnapshot
from fx_smc_bot.research.strategy_alpha_execution import (
    amended_execution_policy,
    amended_session_cutoff,
    is_amended_session_bar,
)

REPO = Path(__file__).resolve().parents[2]


class EmittingRuntime:
    family = "synthetic_protocol_test"
    pair = TradingPair.EURUSD
    session = "london"

    def __init__(self, signal_bar: int, activation_bar: int | None = None) -> None:
        self.signal_bar = signal_bar
        self.activation_bar = activation_bar
        self.seen: list[int] = []
        self.cancel_reasons: list[str] = []

    def on_bar(self, ctx: CausalBarContext) -> list[OrderIntent]:
        self.seen.append(ctx.bar_idx)
        if ctx.bar_idx != self.signal_bar:
            return []
        return [OrderIntent(
            intent_id=f"intent-{ctx.bar_idx}",
            family=self.family,
            pair=self.pair,
            direction=Direction.LONG,
            entry_price=1.1001,
            stop_loss=1.0900,
            take_profit=1.1100,
            signal_bar=ctx.bar_idx,
            signal_timestamp=ctx.timestamp,
            activation_bar=(
                self.activation_bar
                if self.activation_bar is not None
                else ctx.bar_idx + 1
            ),
            expiry_bars=20,
            session=self.session,
        )]

    def on_order_accepted(self, event: object) -> None:
        pass

    def on_order_filled(self, event: object) -> None:
        pass

    def on_order_cancelled(self, event: object) -> None:
        self.cancel_reasons.append(str(getattr(event, "reason", "")))

    def on_position_closed(self, event: object) -> None:
        pass

    def snapshot_state(self) -> dict:
        return {}

    def reset(self) -> None:
        pass


def _series(start: str, bars: int) -> BidAskBarSeries:
    timestamps = np.asarray(
        [np.datetime64(start) + np.timedelta64(5 * idx, "m") for idx in range(bars)],
        dtype="datetime64[ns]",
    )
    bid = np.full(bars, 1.1000, dtype=np.float64)
    ask = np.full(bars, 1.1001, dtype=np.float64)
    return BidAskBarSeries(
        pair=TradingPair.EURUSD,
        timeframe=Timeframe.M5,
        timestamps=timestamps,
        bid_open=bid.copy(),
        bid_high=bid + 0.0002,
        bid_low=bid - 0.0002,
        bid_close=bid.copy(),
        ask_open=ask.copy(),
        ask_high=ask + 0.0002,
        ask_low=ask - 0.0002,
        ask_close=ask.copy(),
    )


def _snapshot(series: object, *_: object) -> StructureSnapshot:
    return StructureSnapshot(
        pair=series.pair,
        timeframe=series.timeframe,
        bar_index=len(series) - 1,
    )


def _policy(**changes: object) -> IntradayExecutionPolicy:
    base = IntradayExecutionPolicy(
        warmup_bars=0,
        close_at_final_bar=True,
        apply_swap=False,
        structure_lookback_bars=20,
        snapshot_builder=_snapshot,
    )
    return replace(base, **changes)


def _config() -> AppConfig:
    return AppConfig(
        execution=ExecutionConfig(slippage_pips=0.0),
        backtest=BacktestConfig(commission_per_lot=0.0),
    )


def test_amended_policy_binds_exact_warmup_and_no_carry() -> None:
    policy = amended_execution_policy()
    assert policy.warmup_bars == 500
    assert policy.close_at_session_cutoff is True
    assert policy.close_at_fx_week_end is True
    assert policy.close_at_final_bar is True
    assert policy.apply_swap is False
    assert policy.fixed_risk_cash == 500.0


def test_engine_enforces_exact_activation_bar() -> None:
    runtime = EmittingRuntime(signal_bar=0, activation_bar=2)
    engine = IntradayBacktestEngine(_config(), execution_policy=_policy())
    engine.add_runtime(runtime)
    engine.run({TradingPair.EURUSD: _series("2019-01-07T08:00", 4)})

    records = engine.get_trade_records()
    assert len(records) == 1
    assert records[0].entry_bar == 2
    assert records[0].exit_reason == "final_available_certified_bar"


def test_engine_closes_on_last_bar_before_session_cutoff() -> None:
    runtime = EmittingRuntime(signal_bar=0)
    policy = _policy(
        close_at_session_cutoff=True,
        session_cutoff_resolver=amended_session_cutoff,
    )
    engine = IntradayBacktestEngine(_config(), execution_policy=policy)
    engine.add_runtime(runtime)
    engine.run({TradingPair.EURUSD: _series("2019-01-07T10:45", 3)})

    record = engine.get_trade_records()[0]
    assert record.entry_bar == 1
    assert record.exit_bar == 2
    assert record.exit_reason == "originating_session_cutoff"
    assert engine.get_funnels()[0].session_exits == 1


def test_cutoff_gap_uses_final_executable_quote_before_boundary() -> None:
    runtime = EmittingRuntime(signal_bar=0)
    series = _series("2019-01-07T10:45", 3)
    series.timestamps[2] = np.datetime64("2019-01-07T11:05")
    policy = _policy(
        close_at_session_cutoff=True,
        session_cutoff_resolver=amended_session_cutoff,
    )
    engine = IntradayBacktestEngine(_config(), execution_policy=policy)
    engine.add_runtime(runtime)
    engine.run({TradingPair.EURUSD: series})

    record = engine.get_trade_records()[0]
    assert record.entry_bar == 1
    assert record.exit_bar == 1
    assert record.exit_reason == "originating_session_cutoff"


def test_signal_on_terminal_session_bar_cannot_create_order() -> None:
    runtime = EmittingRuntime(signal_bar=0)
    policy = _policy(
        close_at_session_cutoff=True,
        session_cutoff_resolver=amended_session_cutoff,
    )
    engine = IntradayBacktestEngine(_config(), execution_policy=policy)
    engine.add_runtime(runtime)
    engine.run({TradingPair.EURUSD: _series("2019-01-07T10:55", 2)})

    funnel = engine.get_funnels()[0]
    assert funnel.intents_generated == 1
    assert funnel.orders_accepted == 0
    assert funnel.session_horizon_signal_rejections == 1
    assert engine.get_trade_records() == []


def test_engine_bidask_conflict_is_adverse_first() -> None:
    runtime = EmittingRuntime(signal_bar=0)
    series = _series("2019-01-07T08:00", 3)
    series.bid_low[2] = 1.0890
    series.bid_high[2] = 1.1110
    engine = IntradayBacktestEngine(_config(), execution_policy=_policy())
    engine.add_runtime(runtime)
    engine.run({TradingPair.EURUSD: series})

    record = engine.get_trade_records()[0]
    assert record.exit_reason == "stop_loss_hit"
    assert engine.get_funnels()[0].sl_exits == 1


def test_warmup_blocks_runtime_until_completed() -> None:
    runtime = EmittingRuntime(signal_bar=500)
    engine = IntradayBacktestEngine(
        _config(),
        execution_policy=_policy(warmup_bars=500),
    )
    engine.add_runtime(runtime)
    engine.run({TradingPair.EURUSD: _series("2019-01-01T00:00", 502)})
    assert runtime.seen[0] == 500
    assert all(index >= 500 for index in runtime.seen)


def test_invalid_executable_quote_fails_closed() -> None:
    series = _series("2019-01-07T08:00", 2)
    series.ask_close[1] = np.nan
    engine = IntradayBacktestEngine(_config(), execution_policy=_policy())
    with pytest.raises(ValueError, match="EXECUTION_DATA_MISSING"):
        engine.run({TradingPair.EURUSD: series})


def test_invalid_trade_geometry_is_rejected_before_order_creation() -> None:
    class InvalidRuntime(EmittingRuntime):
        def on_bar(self, ctx: CausalBarContext) -> list[OrderIntent]:
            intents = super().on_bar(ctx)
            for intent in intents:
                intent.stop_loss = intent.entry_price
            return intents

    runtime = InvalidRuntime(signal_bar=0)
    engine = IntradayBacktestEngine(_config(), execution_policy=_policy())
    engine.add_runtime(runtime)
    engine.run({TradingPair.EURUSD: _series("2019-01-07T08:00", 2)})
    funnel = engine.get_funnels()[0]
    assert funnel.invalid_signal_rejections == 1
    assert funnel.orders_accepted == 0
    assert engine.get_trade_records() == []


def test_amended_session_filter_and_cutoff_are_dst_aware() -> None:
    assert is_amended_session_bar(datetime(2019, 1, 7, 8, 0), "london")
    assert is_amended_session_bar(datetime(2019, 7, 8, 7, 0), "london")
    assert amended_session_cutoff(
        datetime(2019, 1, 7, 8, 0), "london"
    ) == datetime(2019, 1, 7, 11, 0)
    assert amended_session_cutoff(
        datetime(2019, 7, 8, 7, 0), "london"
    ) == datetime(2019, 7, 8, 10, 0)


def test_opening_range_configs_resolve_per_session() -> None:
    path = REPO / "configs/research/intraday_smc/opening_range.yaml"
    london = resolve_runtime_config(
        "opening_range_displacement_fvg_retest",
        TradingPair.EURUSD,
        "london",
        path,
    )
    new_york = resolve_runtime_config(
        "opening_range_displacement_fvg_retest",
        TradingPair.EURUSD,
        "new_york",
        path,
    )
    assert london.config["tz_name"] == "Europe/London"
    assert new_york.config["tz_name"] == "America/New_York"
    assert london.config_hash != new_york.config_hash
