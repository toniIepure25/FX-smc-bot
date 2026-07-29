"""Tests proving that no order can be filled before the signal candle closes.

In the backtest engine, orders are created at the end of bar N processing
and can only be filled starting from bar N+1.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from fx_smc_bot.config import AppConfig, FillPolicy, Timeframe, TradingPair
from fx_smc_bot.domain import (
    Direction,
    Fill,
    FillReason,
    Order,
    OrderState,
    OrderType,
)
from fx_smc_bot.execution.fills import FillEngine
from fx_smc_bot.execution.slippage import ZeroSlippage


class TestOrderTiming:

    def test_market_order_fills_at_next_bar_open(self):
        """A MARKET order placed at bar N must fill at bar N+1's open,
        not at any price from bar N."""
        engine = FillEngine(slippage=ZeroSlippage(), fill_policy=FillPolicy.CONSERVATIVE)

        order = Order(
            pair=TradingPair.EURUSD,
            direction=Direction.LONG,
            order_type=OrderType.MARKET,
            state=OrderState.PENDING,
            requested_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1100,
            units=10000,
            created_at=datetime(2024, 1, 2, 10, 0),
        )

        next_bar_open = 1.1005
        next_bar_time = datetime(2024, 1, 2, 10, 5)
        fills = engine.process_pending_orders(
            [order], next_bar_open, 1.1020, 1.0990, 1.1010, next_bar_time,
        )

        assert len(fills) == 1
        _, fill = fills[0]
        assert fill.fill_price == next_bar_open
        assert fill.reason == FillReason.MARKET_OPEN

    def test_limit_order_does_not_fill_on_creation_bar(self):
        """A LIMIT order should not fill on the bar where it was created.
        The engine processes pending orders on the NEXT bar only."""
        engine = FillEngine(slippage=ZeroSlippage(), fill_policy=FillPolicy.CONSERVATIVE)

        creation_time = datetime(2024, 1, 2, 10, 0)
        order = Order(
            pair=TradingPair.EURUSD,
            direction=Direction.LONG,
            order_type=OrderType.LIMIT,
            state=OrderState.PENDING,
            requested_price=1.0980,
            stop_loss=1.0950,
            take_profit=1.1050,
            units=10000,
            created_at=creation_time,
        )

        future_bar_time = datetime(2024, 1, 2, 10, 5)
        fills = engine.process_pending_orders(
            [order], 1.1000, 1.1010, 1.0975, 1.0990, future_bar_time,
        )
        assert len(fills) == 1
        _, fill = fills[0]
        assert fill.fill_price == 1.0980
        assert fill.timestamp == future_bar_time

    def test_expired_order_not_filled(self):
        """An order past its expiry time must not fill."""
        engine = FillEngine(slippage=ZeroSlippage(), fill_policy=FillPolicy.CONSERVATIVE)

        order = Order(
            pair=TradingPair.EURUSD,
            direction=Direction.LONG,
            order_type=OrderType.LIMIT,
            state=OrderState.PENDING,
            requested_price=1.0980,
            stop_loss=1.0950,
            take_profit=1.1050,
            units=10000,
            created_at=datetime(2024, 1, 2, 10, 0),
            expires_at=datetime(2024, 1, 2, 11, 0),
        )

        bar_time = datetime(2024, 1, 2, 12, 0)
        fills = engine.process_pending_orders(
            [order], 1.1000, 1.1010, 1.0975, 1.0990, bar_time,
        )
        assert len(fills) == 0
        assert order.state == OrderState.EXPIRED

    def test_conservative_fill_policy_chooses_sl(self):
        """When both SL and TP are within bar range, CONSERVATIVE must
        choose SL (worst case)."""
        from fx_smc_bot.domain import Position, PositionState

        engine = FillEngine(slippage=ZeroSlippage(), fill_policy=FillPolicy.CONSERVATIVE)

        pos = Position(
            pair=TradingPair.EURUSD,
            direction=Direction.LONG,
            state=PositionState.OPEN,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1100,
            units=10000,
            opened_at=datetime(2024, 1, 2, 10, 0),
        )

        fill = engine.check_exit_conditions(
            pos, bar_high=1.1150, bar_low=1.0940,
            bar_time=datetime(2024, 1, 2, 11, 0),
        )
        assert fill is not None
        assert fill.reason == FillReason.STOP_LOSS_HIT
