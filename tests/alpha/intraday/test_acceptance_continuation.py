"""Tests for the acceptance continuation strategy."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from fx_smc_bot.config import Timeframe, TradingPair
from fx_smc_bot.domain import (
    Direction,
    FVGZone,
    LiquidityLevel,
    LiquidityLevelType,
    StructureRegime,
    StructureSnapshot,
)
from fx_smc_bot.alpha.intraday.acceptance_continuation import (
    AcceptanceContinuationConfig,
    AcceptanceContinuationDetector,
)
from fx_smc_bot.alpha.intraday.state_machine import StrategyState


def _make_snapshot(
    levels=None, fvgs=None,
) -> StructureSnapshot:
    return StructureSnapshot(
        pair=TradingPair.EURUSD, timeframe=Timeframe.M5,
        bar_index=0, regime=StructureRegime.RANGING,
        swings=[], breaks=[], liquidity_levels=levels or [],
        active_fvgs=fvgs or [], active_order_blocks=[],
        displacements=[], session_windows=[],
    )


class TestAcceptanceContinuation:

    def test_false_breakout_no_acceptance(self):
        """A wick beyond the level followed by close back inside is NOT acceptance."""
        cfg = AcceptanceContinuationConfig(
            acceptance_consecutive_closes=2,
            max_acceptance_bars=3,
            k_atr_break=0.0, k_spread_break=0.0, min_pips_break=0.0,
            displacement_body_ratio=1.0, displacement_tr_ratio=1.0,
            displacement_clv=0.0,
        )
        det = AcceptanceContinuationDetector(config=cfg)

        level = LiquidityLevel(
            price=1.1050, level_type=LiquidityLevelType.EQUAL_HIGHS,
            touch_count=2, formation_index=0,
            formation_time=datetime(2024, 1, 2),
        )

        n = 10
        open_ = np.full(n, 1.104)
        high = np.full(n, 1.106)
        low = np.full(n, 1.103)
        close = np.full(n, 1.104)
        close[3] = 1.1060  # one close above: break
        close[4] = 1.1040  # close back below: no acceptance

        base_time = datetime(2024, 1, 2, 8, 0)
        for i in range(n):
            snap = _make_snapshot(levels=[level])
            snap.bar_index = i
            det.process_bar(
                snap, open_, high, low, close,
                bar_idx=i, bar_time=base_time + timedelta(minutes=i * 5),
                atr=0.001, spread=0.00015,
            )

        invalidated = [
            inst for inst in det.tracker.completed_instances
            if inst.state == StrategyState.INVALIDATED
        ]
        signals_generated = any(
            inst.state == StrategyState.ORDER_PENDING
            for inst in det.tracker.active_instances
        )
        assert not signals_generated

    def test_valid_acceptance_with_retest(self):
        """Break with displacement + consecutive closes + FVG -> signal."""
        cfg = AcceptanceContinuationConfig(
            acceptance_consecutive_closes=2,
            max_acceptance_bars=5,
            max_retest_bars=10,
            k_atr_break=0.0, k_spread_break=0.0, min_pips_break=0.0,
            displacement_body_ratio=1.0, displacement_tr_ratio=1.0,
            displacement_clv=0.0,
            fvg_min_atr=0.0,
        )
        det = AcceptanceContinuationDetector(config=cfg)

        level = LiquidityLevel(
            price=1.1050, level_type=LiquidityLevelType.EQUAL_HIGHS,
            touch_count=2, formation_index=0,
            formation_time=datetime(2024, 1, 2),
        )

        fvg = FVGZone(
            high=1.1080, low=1.1060, direction=Direction.LONG,
            bar_index=6, timestamp=datetime(2024, 1, 2, 0, 30),
            size_atr=0.5,
        )

        n = 10
        open_ = np.array([1.103, 1.1035, 1.104, 1.1040, 1.1055, 1.1065, 1.107, 1.107, 1.107, 1.107])
        high =  np.array([1.105, 1.105,  1.105, 1.107,  1.107,  1.108,  1.109, 1.109, 1.109, 1.109])
        low =   np.array([1.103, 1.103,  1.103, 1.103,  1.104,  1.105,  1.106, 1.106, 1.106, 1.106])
        close = np.array([1.1035, 1.104, 1.1035, 1.106, 1.1065, 1.107,  1.108, 1.108, 1.108, 1.108])

        all_signals = []
        base_time = datetime(2024, 1, 2, 8, 0)
        for i in range(n):
            snap = _make_snapshot(
                levels=[level],
                fvgs=[fvg] if i >= 7 else [],
            )
            snap.bar_index = i
            signals = det.process_bar(
                snap, open_, high, low, close,
                bar_idx=i, bar_time=base_time + timedelta(minutes=i * 5),
                atr=0.001, spread=0.00015,
            )
            all_signals.extend(signals)

        assert len(all_signals) >= 1
        sig = all_signals[0]
        assert sig.direction == Direction.LONG
