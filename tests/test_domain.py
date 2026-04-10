"""Tests for core domain models."""

from __future__ import annotations

from datetime import datetime

import pytest

from fx_smc_bot.config import Timeframe, TradingPair
from fx_smc_bot.domain import (
    BreakType,
    ClosedTrade,
    Direction,
    FVGZone,
    Fill,
    FillReason,
    MarketBar,
    Order,
    OrderBlock,
    OrderState,
    OrderType,
    Position,
    PositionState,
    RiskSnapshot,
    SignalFamily,
    StructureBreak,
    StructureLevel,
    SwingPoint,
    SwingType,
    TradeCandidate,
)


class TestMarketBar:
    def test_creation(self) -> None:
        bar = MarketBar(
            pair=TradingPair.EURUSD,
            timeframe=Timeframe.M15,
            timestamp=datetime(2024, 1, 2, 8, 0),
            open=1.1000, high=1.1010, low=1.0990, close=1.1005,
            bar_index=0,
        )
        assert bar.pair == TradingPair.EURUSD
        assert bar.high > bar.low

    def test_optional_fields(self) -> None:
        bar = MarketBar(
            pair=TradingPair.USDJPY, timeframe=Timeframe.H1,
            timestamp=datetime(2024, 1, 2), open=148.0, high=148.5,
            low=147.5, close=148.2,
        )
        assert bar.volume is None
        assert bar.spread is None
        assert bar.bar_index == 0


class TestSwingPoint:
    def test_frozen(self) -> None:
        sp = SwingPoint(
            bar_index=10, price=1.1050, swing_type=SwingType.HIGH,
            timestamp=datetime(2024, 1, 2), strength=3,
        )
        assert sp.swing_type == SwingType.HIGH
        # Frozen: mutation should raise
        try:
            sp.price = 1.2  # type: ignore[misc]
            assert False, "Should have raised"
        except AttributeError:
            pass


class TestStructureBreak:
    def test_bos(self) -> None:
        swing = SwingPoint(
            bar_index=5, price=1.1050, swing_type=SwingType.HIGH,
            timestamp=datetime(2024, 1, 2),
        )
        brk = StructureBreak(
            break_type=BreakType.BOS, direction=Direction.LONG,
            level=StructureLevel.EXTERNAL, swing_broken=swing,
            break_bar_index=12, break_price=1.1055,
            timestamp=datetime(2024, 1, 2, 3, 0),
        )
        assert brk.break_type == BreakType.BOS
        assert brk.direction == Direction.LONG


class TestFVGZone:
    def test_immutable(self) -> None:
        fvg = FVGZone(
            high=1.1020, low=1.1000, direction=Direction.LONG,
            bar_index=15, timestamp=datetime(2024, 1, 2),
            size_atr=0.8,
        )
        assert fvg.filled_pct == 0.0
        assert not fvg.invalidated


class TestTradeCandidate:
    def test_reward_risk(self) -> None:
        tc = TradeCandidate(
            pair=TradingPair.EURUSD, direction=Direction.LONG,
            family=SignalFamily.SWEEP_REVERSAL,
            timestamp=datetime(2024, 1, 2),
            entry=1.1000, stop_loss=1.0970, take_profit=1.1090,
            signal_score=0.8, structure_score=0.7, liquidity_score=0.9,
            execution_timeframe=Timeframe.M15, context_timeframe=Timeframe.H4,
        )
        assert abs(tc.risk_distance - 0.003) < 1e-10
        assert abs(tc.reward_distance - 0.009) < 1e-10
        assert abs(tc.reward_risk_ratio - 3.0) < 1e-10


class TestOrder:
    def test_defaults(self) -> None:
        order = Order()
        assert order.state == OrderState.PENDING
        assert len(order.id) == 12


class TestPosition:
    def test_unrealized_pnl_long(self) -> None:
        pos = Position(
            pair=TradingPair.EURUSD, direction=Direction.LONG,
            entry_price=1.1000, units=100_000,
        )
        assert pos.unrealized_pnl(1.1050) == pytest.approx(500.0, abs=0.01)

    def test_unrealized_pnl_short(self) -> None:
        pos = Position(
            pair=TradingPair.GBPUSD, direction=Direction.SHORT,
            entry_price=1.2700, units=100_000,
        )
        assert pos.unrealized_pnl(1.2650) == pytest.approx(500.0, abs=0.01)
        assert pos.unrealized_pnl(1.2750) == pytest.approx(-500.0, abs=0.01)


class TestRiskSnapshot:
    def test_frozen(self) -> None:
        snap = RiskSnapshot(
            timestamp=datetime(2024, 1, 2), equity=100_000,
            open_risk=0.005, daily_drawdown=0.01, weekly_drawdown=0.02,
            peak_equity=101_000, throttle_factor=1.0,
            open_position_count=1,
            currency_exposures={"USD": -50000, "EUR": 50000},
        )
        assert snap.throttle_factor == 1.0
