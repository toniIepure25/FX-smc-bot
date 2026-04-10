"""Tests for advanced risk constraints, lockout, and exposure management."""

from __future__ import annotations

from datetime import datetime

import pytest

from fx_smc_bot.config import OperationalState, RiskConfig
from fx_smc_bot.domain import Direction, Position, PositionIntent, TradeCandidate
from fx_smc_bot.config import TradingPair, Timeframe
from fx_smc_bot.domain import SignalFamily
from fx_smc_bot.risk.constraints import (
    CurrencyExposureConstraint,
    DailyStopConstraint,
    DirectionalConcentrationConstraint,
    MaxDailyTradesConstraint,
    build_full_constraints,
    check_all_constraints,
)
from fx_smc_bot.risk.drawdown import DrawdownTracker


def _make_candidate(pair=TradingPair.EURUSD, direction=Direction.LONG) -> TradeCandidate:
    return TradeCandidate(
        pair=pair, direction=direction, family=SignalFamily.SWEEP_REVERSAL,
        timestamp=datetime(2024, 1, 1), entry=1.1000, stop_loss=1.0950,
        take_profit=1.1100, signal_score=0.6, structure_score=0.7,
        liquidity_score=0.5, execution_timeframe=Timeframe.M15,
        context_timeframe=Timeframe.H4,
    )


def _make_intent(pair=TradingPair.EURUSD, direction=Direction.LONG) -> PositionIntent:
    return PositionIntent(
        candidate=_make_candidate(pair, direction),
        risk_fraction=0.005, units=10000, notional=11000, portfolio_weight=0.33,
    )


def _make_position(pair=TradingPair.EURUSD, direction=Direction.LONG) -> Position:
    return Position(
        pair=pair, direction=direction, entry_price=1.1000,
        stop_loss=1.0950, take_profit=1.1100, units=10000,
    )


class TestCurrencyExposureConstraint:
    def test_allows_within_limits(self) -> None:
        constraint = CurrencyExposureConstraint()
        intent = _make_intent()
        passed, _ = constraint.check(intent, [], RiskConfig(), 100_000)
        assert passed

    def test_rejects_excessive_exposure(self) -> None:
        constraint = CurrencyExposureConstraint()
        cfg = RiskConfig(max_currency_exposure=0.05)
        positions = [_make_position() for _ in range(3)]
        intent = _make_intent()
        passed, reason = constraint.check(intent, positions, cfg, 100_000)
        assert not passed
        assert reason is not None


class TestDirectionalConcentration:
    def test_allows_balanced(self) -> None:
        constraint = DirectionalConcentrationConstraint()
        pos = [_make_position(direction=Direction.SHORT)]
        intent = _make_intent(direction=Direction.LONG)
        passed, _ = constraint.check(intent, pos, RiskConfig(), 100_000)
        assert passed


class TestMaxDailyTradesConstraint:
    def test_tracks_daily_count(self) -> None:
        constraint = MaxDailyTradesConstraint()
        cfg = RiskConfig(max_trades_per_day=2)
        now = datetime(2024, 1, 1, 10, 0)

        constraint.record_trade(now)
        constraint.record_trade(now)

        intent = _make_intent()
        passed, _ = constraint.check(intent, [], cfg, 100_000)
        assert not passed

    def test_resets_on_new_day(self) -> None:
        constraint = MaxDailyTradesConstraint()
        cfg = RiskConfig(max_trades_per_day=2)

        constraint.record_trade(datetime(2024, 1, 1, 10, 0))
        constraint.record_trade(datetime(2024, 1, 1, 11, 0))
        constraint.record_trade(datetime(2024, 1, 2, 9, 0))

        intent = _make_intent()
        passed, _ = constraint.check(intent, [], cfg, 100_000)
        assert passed


class TestDailyStopConstraint:
    def test_locks_on_daily_loss(self) -> None:
        constraint = DailyStopConstraint()
        now = datetime(2024, 1, 1, 14, 0)
        constraint.update(0.03, now, 0.025)
        assert constraint.is_locked

        intent = _make_intent()
        passed, reason = constraint.check(intent, [], RiskConfig(), 100_000)
        assert not passed
        assert "locked" in reason.lower()

    def test_unlocks_on_new_day(self) -> None:
        constraint = DailyStopConstraint()
        constraint.update(0.03, datetime(2024, 1, 1, 14, 0), 0.025)
        assert constraint.is_locked

        constraint.update(0.0, datetime(2024, 1, 2, 9, 0), 0.025)
        assert not constraint.is_locked


class TestDrawdownTrackerState:
    def test_consecutive_loss_dampening(self) -> None:
        cfg = RiskConfig(consecutive_loss_dampen_after=2, consecutive_loss_dampen_factor=0.5)
        tracker = DrawdownTracker(100_000, cfg)
        tracker.record_trade_result(-100)
        tracker.record_trade_result(-100)
        tracker.record_trade_result(-100)

        snap = tracker.update(99_000, datetime(2024, 1, 1, 12, 0))
        assert snap.throttle_factor < 1.0

    def test_win_resets_consecutive_losses(self) -> None:
        cfg = RiskConfig()
        tracker = DrawdownTracker(100_000, cfg)
        tracker.record_trade_result(-100)
        tracker.record_trade_result(-100)
        tracker.record_trade_result(200)
        assert tracker.consecutive_losses == 0

    def test_locked_state_on_large_daily_loss(self) -> None:
        cfg = RiskConfig(daily_loss_lockout=0.02)
        tracker = DrawdownTracker(100_000, cfg)
        tracker.update(100_000, datetime(2024, 1, 1, 9, 0))
        tracker.update(97_000, datetime(2024, 1, 1, 15, 0))
        assert tracker.operational_state == OperationalState.LOCKED

    def test_locked_resets_on_new_day(self) -> None:
        cfg = RiskConfig(daily_loss_lockout=0.02)
        tracker = DrawdownTracker(100_000, cfg)
        tracker.update(100_000, datetime(2024, 1, 1, 9, 0))
        tracker.update(97_000, datetime(2024, 1, 1, 15, 0))
        assert tracker.operational_state == OperationalState.LOCKED
        tracker.update(97_000, datetime(2024, 1, 2, 9, 0))
        assert tracker.operational_state != OperationalState.LOCKED


class TestBuildFullConstraints:
    def test_returns_all_constraint_types(self) -> None:
        constraints = build_full_constraints()
        assert len(constraints) >= 6
