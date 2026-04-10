"""Tests for risk constraints."""

from __future__ import annotations

from datetime import datetime

from fx_smc_bot.config import RiskConfig, Timeframe, TradingPair
from fx_smc_bot.domain import (
    Direction,
    Position,
    PositionIntent,
    SignalFamily,
    TradeCandidate,
)
from fx_smc_bot.risk.constraints import (
    MaxConcurrentPositionsConstraint,
    MaxPairPositionsConstraint,
    check_all_constraints,
)


def _intent(pair: TradingPair = TradingPair.EURUSD, risk: float = 0.005) -> PositionIntent:
    tc = TradeCandidate(
        pair=pair, direction=Direction.LONG,
        family=SignalFamily.BOS_CONTINUATION,
        timestamp=datetime(2024, 1, 2),
        entry=1.1, stop_loss=1.097, take_profit=1.109,
        signal_score=0.7, structure_score=0.6, liquidity_score=0.5,
        execution_timeframe=Timeframe.M15, context_timeframe=Timeframe.H4,
    )
    return PositionIntent(candidate=tc, risk_fraction=risk, units=50000, notional=55000, portfolio_weight=0.55)


def _open_position(pair: TradingPair = TradingPair.EURUSD) -> Position:
    return Position(pair=pair, direction=Direction.LONG, entry_price=1.1, stop_loss=1.097, units=50000)


class TestConstraints:
    def test_max_concurrent_blocks(self) -> None:
        cfg = RiskConfig(max_concurrent_positions=2)
        positions = [_open_position(), _open_position()]
        constraint = MaxConcurrentPositionsConstraint()
        passed, reason = constraint.check(_intent(), positions, cfg, 100_000)
        assert not passed

    def test_max_pair_blocks(self) -> None:
        cfg = RiskConfig(max_per_pair_positions=1)
        positions = [_open_position(TradingPair.EURUSD)]
        constraint = MaxPairPositionsConstraint()
        passed, reason = constraint.check(_intent(TradingPair.EURUSD), positions, cfg, 100_000)
        assert not passed

    def test_different_pair_passes(self) -> None:
        cfg = RiskConfig(max_per_pair_positions=1)
        positions = [_open_position(TradingPair.GBPUSD)]
        constraint = MaxPairPositionsConstraint()
        passed, _ = constraint.check(_intent(TradingPair.EURUSD), positions, cfg, 100_000)
        assert passed

    def test_all_constraints_pass_when_clean(self) -> None:
        cfg = RiskConfig()
        passed, reasons = check_all_constraints(_intent(), [], cfg, 100_000)
        assert passed
        assert len(reasons) == 0
