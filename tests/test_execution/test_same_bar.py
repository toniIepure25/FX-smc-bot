"""Tests for same-bar SL/TP exit checks."""

from __future__ import annotations

from datetime import datetime

import pytest

from fx_smc_bot.config import FillPolicy, TradingPair
from fx_smc_bot.domain import (
    Direction,
    FillReason,
    Position,
    PositionState,
)
from fx_smc_bot.execution.fills import FillEngine
from fx_smc_bot.execution.slippage import ZeroSlippage


class TestSameBarExit:

    def test_conservative_same_bar_sl(self):
        """Under CONSERVATIVE, same-bar exit should check SL only."""
        engine = FillEngine(
            slippage=ZeroSlippage(),
            fill_policy=FillPolicy.CONSERVATIVE,
        )
        pos = Position(
            pair=TradingPair.EURUSD,
            direction=Direction.LONG,
            state=PositionState.OPEN,
            entry_price=1.1000,
            stop_loss=1.0960,
            take_profit=1.1060,
            units=10000,
            opened_at=datetime(2024, 1, 2, 10, 0),
        )

        fill = engine.check_same_bar_exit(
            pos, fill_price=1.1000,
            bar_high=1.1050, bar_low=1.0950,
            bar_time=datetime(2024, 1, 2, 10, 0),
        )
        assert fill is not None
        assert fill.reason == FillReason.STOP_LOSS_HIT

    def test_conservative_same_bar_no_tp(self):
        """CONSERVATIVE should NOT trigger TP on same bar even if in range."""
        engine = FillEngine(
            slippage=ZeroSlippage(),
            fill_policy=FillPolicy.CONSERVATIVE,
        )
        pos = Position(
            pair=TradingPair.EURUSD,
            direction=Direction.LONG,
            state=PositionState.OPEN,
            entry_price=1.1000,
            stop_loss=1.0900,
            take_profit=1.1020,
            units=10000,
            opened_at=datetime(2024, 1, 2, 10, 0),
        )

        fill = engine.check_same_bar_exit(
            pos, fill_price=1.1000,
            bar_high=1.1050, bar_low=1.0950,
            bar_time=datetime(2024, 1, 2, 10, 0),
        )
        assert fill is None  # SL not hit

    def test_optimistic_same_bar_tp(self):
        """OPTIMISTIC should check TP first on same bar."""
        engine = FillEngine(
            slippage=ZeroSlippage(),
            fill_policy=FillPolicy.OPTIMISTIC,
        )
        pos = Position(
            pair=TradingPair.EURUSD,
            direction=Direction.LONG,
            state=PositionState.OPEN,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1020,
            units=10000,
            opened_at=datetime(2024, 1, 2, 10, 0),
        )

        fill = engine.check_same_bar_exit(
            pos, fill_price=1.1000,
            bar_high=1.1050, bar_low=1.0990,
            bar_time=datetime(2024, 1, 2, 10, 0),
        )
        assert fill is not None
        assert fill.reason == FillReason.TAKE_PROFIT_HIT

    def test_no_exit_if_position_closed(self):
        engine = FillEngine(slippage=ZeroSlippage())
        pos = Position(
            pair=TradingPair.EURUSD,
            direction=Direction.LONG,
            state=PositionState.CLOSED,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1020,
            units=10000,
        )
        fill = engine.check_same_bar_exit(
            pos, 1.1000, 1.1050, 1.0900, datetime(2024, 1, 2),
        )
        assert fill is None
