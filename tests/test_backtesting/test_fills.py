"""Tests for fill engine with configurable fill policies."""

from __future__ import annotations

from datetime import datetime

import pytest

from fx_smc_bot.config import FillPolicy, TradingPair
from fx_smc_bot.domain import (
    Direction,
    FillReason,
    Order,
    OrderState,
    OrderType,
    Position,
    PositionState,
)
from fx_smc_bot.execution.fills import FillEngine
from fx_smc_bot.execution.slippage import ZeroSlippage


@pytest.fixture
def zero_engine() -> FillEngine:
    return FillEngine(slippage=ZeroSlippage())


@pytest.fixture
def conservative_engine() -> FillEngine:
    return FillEngine(slippage=ZeroSlippage(), fill_policy=FillPolicy.CONSERVATIVE)


@pytest.fixture
def optimistic_engine() -> FillEngine:
    return FillEngine(slippage=ZeroSlippage(), fill_policy=FillPolicy.OPTIMISTIC)


@pytest.fixture
def long_position() -> Position:
    return Position(
        pair=TradingPair.EURUSD, direction=Direction.LONG,
        state=PositionState.OPEN, entry_price=1.1000,
        stop_loss=1.0950, take_profit=1.1100, units=100_000,
    )


@pytest.fixture
def short_position() -> Position:
    return Position(
        pair=TradingPair.EURUSD, direction=Direction.SHORT,
        state=PositionState.OPEN, entry_price=1.1000,
        stop_loss=1.1050, take_profit=1.0900, units=100_000,
    )


class TestFillPolicyConservative:
    def test_sl_only(self, conservative_engine: FillEngine, long_position: Position) -> None:
        fill = conservative_engine.check_exit_conditions(
            long_position, bar_high=1.1050, bar_low=1.0940,
            bar_time=datetime(2024, 1, 2),
        )
        assert fill is not None
        assert fill.reason == FillReason.STOP_LOSS_HIT

    def test_tp_only(self, conservative_engine: FillEngine, long_position: Position) -> None:
        fill = conservative_engine.check_exit_conditions(
            long_position, bar_high=1.1110, bar_low=1.0960,
            bar_time=datetime(2024, 1, 2),
        )
        assert fill is not None
        assert fill.reason == FillReason.TAKE_PROFIT_HIT

    def test_both_hit_takes_sl(self, conservative_engine: FillEngine, long_position: Position) -> None:
        fill = conservative_engine.check_exit_conditions(
            long_position, bar_high=1.1110, bar_low=1.0940,
            bar_time=datetime(2024, 1, 2),
        )
        assert fill is not None
        assert fill.reason == FillReason.STOP_LOSS_HIT


class TestFillPolicyOptimistic:
    def test_both_hit_takes_tp(self, optimistic_engine: FillEngine, long_position: Position) -> None:
        fill = optimistic_engine.check_exit_conditions(
            long_position, bar_high=1.1110, bar_low=1.0940,
            bar_time=datetime(2024, 1, 2),
        )
        assert fill is not None
        assert fill.reason == FillReason.TAKE_PROFIT_HIT


class TestFillPolicyRandom:
    def test_produces_either_result(self, long_position: Position) -> None:
        reasons: set[FillReason] = set()
        for seed in range(50):
            engine = FillEngine(
                slippage=ZeroSlippage(),
                fill_policy=FillPolicy.RANDOM,
                rng_seed=seed,
            )
            fill = engine.check_exit_conditions(
                long_position, bar_high=1.1110, bar_low=1.0940,
                bar_time=datetime(2024, 1, 2),
            )
            assert fill is not None
            reasons.add(fill.reason)
        assert FillReason.STOP_LOSS_HIT in reasons
        assert FillReason.TAKE_PROFIT_HIT in reasons


class TestShortPositionFills:
    def test_short_sl(self, conservative_engine: FillEngine, short_position: Position) -> None:
        fill = conservative_engine.check_exit_conditions(
            short_position, bar_high=1.1060, bar_low=1.0950,
            bar_time=datetime(2024, 1, 2),
        )
        assert fill is not None
        assert fill.reason == FillReason.STOP_LOSS_HIT

    def test_short_tp(self, conservative_engine: FillEngine, short_position: Position) -> None:
        fill = conservative_engine.check_exit_conditions(
            short_position, bar_high=1.1040, bar_low=1.0890,
            bar_time=datetime(2024, 1, 2),
        )
        assert fill is not None
        assert fill.reason == FillReason.TAKE_PROFIT_HIT


class TestPendingOrders:
    def test_market_order_fills_at_open(self, zero_engine: FillEngine) -> None:
        order = Order(
            pair=TradingPair.EURUSD, direction=Direction.LONG,
            order_type=OrderType.MARKET, units=100_000,
            requested_price=1.1000,
        )
        fills = zero_engine.process_pending_orders(
            [order], bar_open=1.1002, bar_high=1.1010,
            bar_low=1.0990, bar_close=1.1005,
            bar_time=datetime(2024, 1, 2),
        )
        assert len(fills) == 1
        assert fills[0][1].fill_price == 1.1002
        assert order.state == OrderState.FILLED
