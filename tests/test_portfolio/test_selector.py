"""Tests for portfolio candidate selection."""

from __future__ import annotations

from datetime import datetime

from fx_smc_bot.config import RiskConfig, Timeframe, TradingPair
from fx_smc_bot.domain import Direction, SignalFamily, TradeCandidate
from fx_smc_bot.portfolio.selector import select_candidates


def _candidate(
    pair: TradingPair = TradingPair.EURUSD,
    score: float = 0.8,
) -> TradeCandidate:
    return TradeCandidate(
        pair=pair, direction=Direction.LONG,
        family=SignalFamily.SWEEP_REVERSAL,
        timestamp=datetime(2024, 1, 2),
        entry=1.1, stop_loss=1.097, take_profit=1.109,
        signal_score=score, structure_score=0.7, liquidity_score=0.8,
        execution_timeframe=Timeframe.M15, context_timeframe=Timeframe.H4,
    )


class TestSelector:
    def test_selects_within_limits(self) -> None:
        cfg = RiskConfig(max_concurrent_positions=2)
        candidates = [
            _candidate(TradingPair.EURUSD, 0.9),
            _candidate(TradingPair.GBPUSD, 0.8),
            _candidate(TradingPair.USDJPY, 0.7),
        ]
        intents = select_candidates(candidates, [], 100_000, cfg)
        assert len(intents) <= 2

    def test_respects_per_pair_limit(self) -> None:
        cfg = RiskConfig(max_per_pair_positions=1, max_concurrent_positions=5)
        candidates = [
            _candidate(TradingPair.EURUSD, 0.9),
            _candidate(TradingPair.EURUSD, 0.8),
        ]
        intents = select_candidates(candidates, [], 100_000, cfg)
        assert len(intents) == 1

    def test_returns_empty_for_no_candidates(self) -> None:
        cfg = RiskConfig()
        intents = select_candidates([], [], 100_000, cfg)
        assert len(intents) == 0
