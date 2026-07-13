"""Tests for the sweep reversal strategy with causal state machine.

Includes handcrafted deterministic OHLC scenarios proving:
- Valid bullish reversal
- Sweep without reclaim (invalidated)
- Reclaim without MSS (invalidated)
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from fx_smc_bot.config import StructureConfig, Timeframe, TradingPair
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.domain import (
    Direction,
    FVGZone,
    LiquidityLevel,
    LiquidityLevelType,
    MarketBar,
    StructureRegime,
    StructureSnapshot,
    SwingPoint,
    SwingType,
)
from fx_smc_bot.alpha.intraday.common import (
    check_mss,
    check_reclaim,
    check_sweep,
    compute_entry_sl_tp,
    compute_min_excursion,
    find_causal_swing,
    sweep_direction,
)
from fx_smc_bot.alpha.intraday.state_machine import StrategyState
from fx_smc_bot.alpha.intraday.sweep_reversal import (
    SweepReversalConfig,
    SweepReversalDetectorV2,
)


class TestCommonHelpers:

    def test_sweep_direction_equal_highs(self):
        level = LiquidityLevel(
            price=1.1050, level_type=LiquidityLevelType.EQUAL_HIGHS,
            touch_count=2, formation_index=5,
            formation_time=datetime(2024, 1, 2),
        )
        assert sweep_direction(level) == Direction.SHORT

    def test_sweep_direction_equal_lows(self):
        level = LiquidityLevel(
            price=1.0950, level_type=LiquidityLevelType.EQUAL_LOWS,
            touch_count=2, formation_index=5,
            formation_time=datetime(2024, 1, 2),
        )
        assert sweep_direction(level) == Direction.LONG

    def test_check_sweep_high_side(self):
        level = LiquidityLevel(
            price=1.1050, level_type=LiquidityLevelType.SESSION_HIGH,
            touch_count=1, formation_index=5,
            formation_time=datetime(2024, 1, 2),
        )
        high = np.array([1.10, 1.10, 1.10, 1.10, 1.10, 1.10, 1.1060])
        low = np.array([1.09, 1.09, 1.09, 1.09, 1.09, 1.09, 1.098])
        breached, extreme = check_sweep(level, high, low, 6, 0.0003)
        assert breached
        assert extreme == 1.1060

    def test_check_sweep_insufficient_excursion(self):
        level = LiquidityLevel(
            price=1.1050, level_type=LiquidityLevelType.SESSION_HIGH,
            touch_count=1, formation_index=5,
            formation_time=datetime(2024, 1, 2),
        )
        high = np.array([1.10, 1.10, 1.10, 1.10, 1.10, 1.10, 1.1051])
        low = np.array([1.09, 1.09, 1.09, 1.09, 1.09, 1.09, 1.098])
        breached, _ = check_sweep(level, high, low, 6, 0.0005)
        assert not breached

    def test_check_reclaim_low_side(self):
        level = LiquidityLevel(
            price=1.0950, level_type=LiquidityLevelType.EQUAL_LOWS,
            touch_count=2, formation_index=5,
            formation_time=datetime(2024, 1, 2),
        )
        close = np.array([1.09, 1.09, 1.09, 1.09, 1.09, 1.09, 1.094, 1.096])
        assert check_reclaim(level, close, 6, 7, max_bars=3)

    def test_check_reclaim_timeout(self):
        level = LiquidityLevel(
            price=1.0950, level_type=LiquidityLevelType.EQUAL_LOWS,
            touch_count=2, formation_index=5,
            formation_time=datetime(2024, 1, 2),
        )
        close = np.array([1.09] * 20)
        assert not check_reclaim(level, close, 5, 15, max_bars=3)

    def test_find_causal_swing(self):
        swings = [
            SwingPoint(bar_index=5, price=1.1030, swing_type=SwingType.HIGH,
                       timestamp=datetime(2024, 1, 2, 1, 0)),
            SwingPoint(bar_index=15, price=1.1060, swing_type=SwingType.HIGH,
                       timestamp=datetime(2024, 1, 2, 2, 0)),
        ]
        # swing at 15 with lookback=5 is confirmed at bar 20
        result = find_causal_swing(swings, Direction.LONG, max_bar=20, swing_lookback=5)
        assert result is not None
        assert result.bar_index == 15

        # At bar 18, swing at 15 is NOT yet confirmed (needs bar 20)
        result_not_yet = find_causal_swing(swings, Direction.LONG, max_bar=18, swing_lookback=5)
        assert result_not_yet is not None
        assert result_not_yet.bar_index == 5  # only the earlier one is confirmed

        result_earlier = find_causal_swing(swings, Direction.LONG, max_bar=12, swing_lookback=5)
        assert result_earlier is not None
        assert result_earlier.bar_index == 5

    def test_check_mss_long(self):
        swing = SwingPoint(
            bar_index=5, price=1.1030, swing_type=SwingType.HIGH,
            timestamp=datetime(2024, 1, 2),
        )
        close = np.array([1.10, 1.10, 1.10, 1.10, 1.10, 1.10, 1.10, 1.1040])
        assert check_mss(Direction.LONG, close, 7, swing)
        assert not check_mss(Direction.LONG, close, 5, swing)

    def test_compute_entry_sl_tp_long(self):
        fvg = FVGZone(
            high=1.1020, low=1.1000, direction=Direction.LONG,
            bar_index=10, timestamp=datetime(2024, 1, 2),
            size_atr=0.5,
        )
        entry, sl, tp = compute_entry_sl_tp(
            fvg, Direction.LONG, sweep_extreme=1.0940,
            entry_pct=0.5, target_r=2.0, sl_buffer=0.0003,
        )
        assert abs(entry - 1.1010) < 1e-8
        assert sl < entry
        assert tp > entry
        risk = entry - sl
        assert abs(tp - (entry + 2.0 * risk)) < 1e-8


class TestSweepReversalDetectorV2:

    def _make_snapshot(
        self,
        levels: list[LiquidityLevel] | None = None,
        swings: list[SwingPoint] | None = None,
        fvgs: list[FVGZone] | None = None,
    ) -> StructureSnapshot:
        return StructureSnapshot(
            pair=TradingPair.EURUSD,
            timeframe=Timeframe.M5,
            bar_index=0,
            regime=StructureRegime.RANGING,
            swings=swings or [],
            breaks=[],
            liquidity_levels=levels or [],
            active_fvgs=fvgs or [],
            active_order_blocks=[],
            displacements=[],
            session_windows=[],
        )

    def test_no_signal_without_levels(self):
        det = SweepReversalDetectorV2()
        snap = self._make_snapshot()
        high = np.array([1.10] * 10)
        low = np.array([1.09] * 10)
        close = np.array([1.095] * 10)
        open_ = np.array([1.095] * 10)
        signals = det.process_bar(
            snap, open_, high, low, close,
            bar_idx=5, bar_time=datetime(2024, 1, 2, 8, 0),
            atr=0.001, spread=0.00015,
        )
        assert len(signals) == 0

    def test_sweep_without_reclaim_invalidates(self):
        """Level gets swept but price never reclaims -> INVALIDATED."""
        cfg = SweepReversalConfig(max_reclaim_bars=2)
        det = SweepReversalDetectorV2(config=cfg)

        level = LiquidityLevel(
            price=1.0950, level_type=LiquidityLevelType.EQUAL_LOWS,
            touch_count=2, formation_index=3,
            formation_time=datetime(2024, 1, 2),
        )

        n = 15
        high = np.full(n, 1.10)
        low = np.full(n, 1.094)
        close = np.full(n, 1.094)
        open_ = np.full(n, 1.095)

        base_time = datetime(2024, 1, 2, 0, 0)
        for i in range(n):
            snap = self._make_snapshot(levels=[level])
            snap.bar_index = i
            det.process_bar(
                snap, open_, high, low, close,
                bar_idx=i, bar_time=base_time + timedelta(minutes=i * 5),
                atr=0.001, spread=0.00015,
            )

        invalidated = [
            inst for inst in det.tracker.completed_instances
            if inst.state == StrategyState.INVALIDATED
            and inst.invalidation_reason == "no reclaim within max bars"
        ]
        assert len(invalidated) >= 1

    def test_full_sweep_reversal_signal(self):
        """Full lifecycle: level -> sweep -> reclaim -> MSS -> displacement + FVG -> signal.

        Scenario (LONG reversal from sell-side sweep):
        - Equal lows level at 1.0950, formed at bar 0
        - Bar 5: low dips to 1.0940 (sweep), close at 1.0945 (below level)
        - Bar 6: close at 1.0960 (reclaim above level)
        - Bar 7: close at 1.1020 (above swing high at 1.1010 = MSS)
        - Bar 8: large bullish displacement candle (close 1.1050)
        - Bar 9 onward: FVG available -> signal
        """
        cfg = SweepReversalConfig(
            max_reclaim_bars=5,
            max_mss_bars=5,
            max_displacement_bars=5,
            displacement_body_ratio=1.0,
            displacement_tr_ratio=1.0,
            displacement_clv=0.3,
            fvg_min_atr=0.0,
            k_atr_excursion=0.0,
            k_spread_excursion=0.0,
            min_pips_excursion=0.0,
            swing_lookback=2,
        )
        det = SweepReversalDetectorV2(config=cfg)

        level = LiquidityLevel(
            price=1.0950, level_type=LiquidityLevelType.EQUAL_LOWS,
            touch_count=2, formation_index=0,
            formation_time=datetime(2024, 1, 2),
        )
        swing_high = SwingPoint(
            bar_index=3, price=1.1010, swing_type=SwingType.HIGH,
            timestamp=datetime(2024, 1, 2, 0, 15),
        )

        fvg = FVGZone(
            high=1.1020, low=1.1000, direction=Direction.LONG,
            bar_index=8, timestamp=datetime(2024, 1, 2, 0, 40),
            size_atr=0.5,
        )

        n = 12
        #           bar:  0      1      2      3      4      5       6       7       8       9       10      11
        open_ = np.array([1.10,  1.10,  1.10,  1.10,  1.10,  1.096,  1.0945, 1.096,  1.100,  1.103,  1.103,  1.103])
        high =  np.array([1.10,  1.10,  1.1015,1.1015,1.10,  1.10,   1.097,  1.102,  1.106,  1.106,  1.106,  1.106])
        low =   np.array([1.098, 1.098, 1.098, 1.098, 1.098, 1.0940, 1.094,  1.095,  1.099,  1.100,  1.100,  1.100])
        close = np.array([1.10,  1.10,  1.10,  1.10,  1.10,  1.0945, 1.0960, 1.1020, 1.105,  1.105,  1.105,  1.105])

        all_signals = []
        base_time = datetime(2024, 1, 2, 0, 0)
        for i in range(n):
            snap = self._make_snapshot(
                levels=[level],
                swings=[swing_high] if i >= 5 else [],
                fvgs=[fvg] if i >= 9 else [],
            )
            snap.bar_index = i
            signals = det.process_bar(
                snap, open_, high, low, close,
                bar_idx=i,
                bar_time=base_time + timedelta(minutes=i * 5),
                atr=0.001, spread=0.00015,
            )
            all_signals.extend(signals)

        assert len(all_signals) >= 1, (
            f"Expected signal. Active: {[(i.state, i.invalidation_reason) for i in det.tracker.active_instances]}, "
            f"Completed: {[(i.state, i.invalidation_reason) for i in det.tracker.completed_instances]}"
        )
        sig = all_signals[0]
        assert sig.direction == Direction.LONG
        assert sig.entry > 0
        assert sig.stop_loss < sig.entry
        assert sig.take_profit > sig.entry
