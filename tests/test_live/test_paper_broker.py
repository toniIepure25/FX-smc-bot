"""Tests for PaperBroker state transitions and order lifecycle."""

from __future__ import annotations

from datetime import datetime

import pytest

from fx_smc_bot.config import TradingPair
from fx_smc_bot.domain import Direction, Order, OrderType
from fx_smc_bot.live.broker import PaperBroker


class TestPaperBroker:
    def test_initial_account_state(self) -> None:
        broker = PaperBroker(initial_capital=50_000)
        account = broker.get_account()
        assert account.equity == 50_000
        assert account.cash == 50_000
        assert account.open_position_count == 0

    def test_submit_and_cancel_order(self) -> None:
        broker = PaperBroker()
        order = Order(
            pair=TradingPair.EURUSD, direction=Direction.LONG,
            order_type=OrderType.MARKET, units=10000,
            requested_price=1.1000, stop_loss=1.0950, take_profit=1.1100,
        )
        oid = broker.submit_order(order)
        assert oid
        assert broker.get_account().pending_order_count == 1

        cancelled = broker.cancel_order(oid)
        assert cancelled
        assert broker.get_account().pending_order_count == 0

    def test_cancel_nonexistent_order(self) -> None:
        broker = PaperBroker()
        assert not broker.cancel_order("nonexistent")

    def test_market_order_fills_on_bar(self) -> None:
        broker = PaperBroker(initial_capital=100_000)
        order = Order(
            pair=TradingPair.EURUSD, direction=Direction.LONG,
            order_type=OrderType.MARKET, units=10000,
            requested_price=1.1000, stop_loss=1.0950, take_profit=1.1100,
        )
        broker.submit_order(order)

        fills = broker.process_bar(
            TradingPair.EURUSD, 1.1000, 1.1050, 1.0990, 1.1020,
            datetime(2024, 1, 1, 10, 0),
        )
        assert len(fills) >= 1
        assert broker.get_account().open_position_count == 1

    def test_position_closes_on_sl(self) -> None:
        broker = PaperBroker(initial_capital=100_000)
        order = Order(
            pair=TradingPair.EURUSD, direction=Direction.LONG,
            order_type=OrderType.MARKET, units=10000,
            requested_price=1.1000, stop_loss=1.0900, take_profit=1.1200,
        )
        broker.submit_order(order)
        broker.process_bar(
            TradingPair.EURUSD, 1.1000, 1.1010, 1.0995, 1.1005,
            datetime(2024, 1, 1, 10, 0),
        )
        assert broker.get_account().open_position_count == 1

        fills = broker.process_bar(
            TradingPair.EURUSD, 1.0950, 1.0960, 1.0880, 1.0890,
            datetime(2024, 1, 1, 11, 0),
        )
        assert broker.get_account().open_position_count == 0
        assert len(broker.all_closed_positions) >= 1

    def test_get_positions_returns_only_open(self) -> None:
        broker = PaperBroker()
        assert broker.get_positions() == []
