"""Tests for position sizing strategies."""

from __future__ import annotations

from datetime import datetime

import pytest

from fx_smc_bot.config import RiskConfig, Timeframe, TradingPair
from fx_smc_bot.domain import Direction, SignalFamily, TradeCandidate
from fx_smc_bot.risk.sizing import (
    ScoreAwareSizer,
    StopBasedSizer,
    VolatilityAdjustedSizer,
)


def _make_candidate(
    entry: float = 1.1000,
    sl: float = 1.0970,
    tp: float = 1.1090,
    score: float = 0.8,
) -> TradeCandidate:
    return TradeCandidate(
        pair=TradingPair.EURUSD, direction=Direction.LONG,
        family=SignalFamily.SWEEP_REVERSAL,
        timestamp=datetime(2024, 1, 2),
        entry=entry, stop_loss=sl, take_profit=tp,
        signal_score=score, structure_score=0.7, liquidity_score=0.8,
        execution_timeframe=Timeframe.M15, context_timeframe=Timeframe.H4,
    )


class TestStopBasedSizer:
    def test_basic_sizing(self) -> None:
        sizer = StopBasedSizer()
        cfg = RiskConfig(base_risk_per_trade=0.01)
        candidate = _make_candidate()
        units, risk_frac = sizer.compute(candidate, equity=100_000, risk_cfg=cfg)
        assert units > 0
        assert risk_frac == 0.01

    def test_zero_risk_distance(self) -> None:
        sizer = StopBasedSizer()
        cfg = RiskConfig()
        candidate = _make_candidate(entry=1.1, sl=1.1)
        units, _ = sizer.compute(candidate, equity=100_000, risk_cfg=cfg)
        assert units == 0.0

    def test_higher_risk_gives_more_units(self) -> None:
        sizer = StopBasedSizer()
        cfg_low = RiskConfig(base_risk_per_trade=0.005)
        cfg_high = RiskConfig(base_risk_per_trade=0.01)
        candidate = _make_candidate()
        u_low, _ = sizer.compute(candidate, equity=100_000, risk_cfg=cfg_low)
        u_high, _ = sizer.compute(candidate, equity=100_000, risk_cfg=cfg_high)
        assert u_high > u_low


class TestVolatilityAdjustedSizer:
    def test_high_vol_reduces_size(self) -> None:
        sizer = VolatilityAdjustedSizer()
        cfg = RiskConfig(volatility_risk_scaling=True)
        candidate = _make_candidate()
        u_normal, _ = sizer.compute(candidate, 100_000, cfg, current_atr=0.001, median_atr=0.001)
        u_high_vol, _ = sizer.compute(candidate, 100_000, cfg, current_atr=0.002, median_atr=0.001)
        assert u_high_vol < u_normal

    def test_no_scaling_flag(self) -> None:
        sizer = VolatilityAdjustedSizer()
        cfg = RiskConfig(volatility_risk_scaling=False)
        candidate = _make_candidate()
        u1, _ = sizer.compute(candidate, 100_000, cfg, current_atr=0.002, median_atr=0.001)
        u2, _ = sizer.compute(candidate, 100_000, cfg, current_atr=0.001, median_atr=0.001)
        assert u1 == u2


class TestScoreAwareSizer:
    def test_low_score_reduces_size(self) -> None:
        sizer = ScoreAwareSizer()
        cfg = RiskConfig(score_risk_modulation=0.5)
        c_high = _make_candidate(score=1.0)
        c_low = _make_candidate(score=0.2)
        u_high, _ = sizer.compute(c_high, 100_000, cfg)
        u_low, _ = sizer.compute(c_low, 100_000, cfg)
        assert u_high > u_low
