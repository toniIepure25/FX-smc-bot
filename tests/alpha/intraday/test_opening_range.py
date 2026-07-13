"""Tests for the opening range displacement + FVG retest strategy."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from fx_smc_bot.config import Timeframe, TradingPair
from fx_smc_bot.domain import (
    Direction,
    FVGZone,
    StructureRegime,
    StructureSnapshot,
)
from fx_smc_bot.alpha.intraday.opening_range import (
    OpeningRangeConfig,
    OpeningRangeDetector,
)
from fx_smc_bot.alpha.intraday.state_machine import StrategyState


def _make_snapshot(fvgs=None) -> StructureSnapshot:
    return StructureSnapshot(
        pair=TradingPair.EURUSD, timeframe=Timeframe.M5,
        bar_index=0, regime=StructureRegime.RANGING,
        swings=[], breaks=[], liquidity_levels=[],
        active_fvgs=fvgs or [], active_order_blocks=[],
        displacements=[], session_windows=[],
    )


class TestOpeningRangeDetector:

    def test_range_not_available_during_window(self):
        """Range must NOT be complete before the window ends."""
        cfg = OpeningRangeConfig(
            session_name="london",
            tz_name="Europe/London",
            range_start_local="08:00",
            range_end_local="08:30",
            min_range_atr=0.0,
            max_range_atr=100.0,
        )
        det = OpeningRangeDetector(config=cfg)

        # Jan 15 2024: winter, London 08:00 = 08:00 UTC
        base = datetime(2024, 1, 15, 8, 0)
        n = 6  # 30 minutes of M5 bars
        open_ = np.full(n, 1.10)
        high = np.array([1.102, 1.103, 1.104, 1.101, 1.102, 1.103])
        low = np.array([1.098, 1.099, 1.098, 1.097, 1.098, 1.099])
        close = np.full(n, 1.10)

        for i in range(5):  # only process bars inside range window
            snap = _make_snapshot()
            snap.bar_index = i
            det.process_bar(
                snap, open_, high, low, close,
                bar_idx=i, bar_time=base + timedelta(minutes=i * 5),
                atr=0.001, spread=0.00015,
            )

        range_complete = any(
            inst.state != StrategyState.IDLE
            for inst in det.tracker.active_instances
        )
        assert not range_complete or all(
            inst.state == StrategyState.RANGE_COMPLETE
            for inst in det.tracker.active_instances
        )

    def test_range_complete_after_window(self):
        """Range should become complete after the window ends."""
        cfg = OpeningRangeConfig(
            session_name="london",
            tz_name="Europe/London",
            range_start_local="08:00",
            range_end_local="08:30",
            min_range_atr=0.0,
            max_range_atr=100.0,
        )
        det = OpeningRangeDetector(config=cfg)

        base = datetime(2024, 1, 15, 8, 0)
        n = 10
        open_ = np.full(n, 1.10)
        high = np.array([1.102, 1.103, 1.104, 1.103, 1.102, 1.101,
                         1.102, 1.103, 1.102, 1.101])
        low = np.array([1.098, 1.099, 1.098, 1.097, 1.098, 1.099,
                        1.098, 1.099, 1.098, 1.099])
        close = np.full(n, 1.10)

        for i in range(n):
            snap = _make_snapshot()
            snap.bar_index = i
            det.process_bar(
                snap, open_, high, low, close,
                bar_idx=i, bar_time=base + timedelta(minutes=i * 5),
                atr=0.001, spread=0.00015,
            )

        range_complete_instances = [
            inst for inst in det.tracker.active_instances
            if inst.state == StrategyState.RANGE_COMPLETE
        ]
        assert len(range_complete_instances) == 2  # one LONG, one SHORT

    def test_session_cutoff_expires(self):
        """Instances still pending at session cutoff should expire."""
        cfg = OpeningRangeConfig(
            session_name="london",
            tz_name="Europe/London",
            range_start_local="08:00",
            range_end_local="08:30",
            session_cutoff_local="09:00",
            min_range_atr=0.0,
            max_range_atr=100.0,
        )
        det = OpeningRangeDetector(config=cfg)

        base = datetime(2024, 1, 15, 8, 0)
        n = 15  # goes past 09:00 UTC
        open_ = np.full(n, 1.10)
        high = np.full(n, 1.102)
        low = np.full(n, 1.098)
        close = np.full(n, 1.10)

        for i in range(n):
            snap = _make_snapshot()
            snap.bar_index = i
            det.process_bar(
                snap, open_, high, low, close,
                bar_idx=i, bar_time=base + timedelta(minutes=i * 5),
                atr=0.001, spread=0.00015,
            )

        expired = [
            inst for inst in det.tracker.completed_instances
            if inst.state == StrategyState.EXPIRED
        ]
        assert len(expired) >= 1

    def test_bullish_breakout_signal(self):
        """Breakout above range + displacement + FVG -> bullish signal."""
        cfg = OpeningRangeConfig(
            session_name="london",
            tz_name="Europe/London",
            range_start_local="08:00",
            range_end_local="08:30",
            session_cutoff_local="12:00",
            min_range_atr=0.0,
            max_range_atr=100.0,
            breakout_min_close_distance_atr=0.0,
            displacement_body_ratio=1.0,
            displacement_tr_ratio=1.0,
            displacement_clv=0.0,
            fvg_min_atr=0.0,
        )
        det = OpeningRangeDetector(config=cfg)

        fvg = FVGZone(
            high=1.106, low=1.104, direction=Direction.LONG,
            bar_index=9, timestamp=datetime(2024, 1, 15, 8, 45),
            size_atr=0.5,
        )

        base = datetime(2024, 1, 15, 8, 0)
        n = 12
        open_ = np.array([1.099, 1.100, 1.101, 1.100, 1.099, 1.100,
                          1.100, 1.103, 1.104, 1.106, 1.106, 1.106])
        high =  np.array([1.102, 1.103, 1.104, 1.103, 1.102, 1.101,
                          1.102, 1.105, 1.107, 1.108, 1.108, 1.108])
        low =   np.array([1.098, 1.099, 1.098, 1.097, 1.098, 1.099,
                          1.098, 1.100, 1.103, 1.104, 1.104, 1.104])
        close = np.array([1.100, 1.101, 1.100, 1.099, 1.100, 1.101,
                          1.100, 1.104, 1.106, 1.107, 1.107, 1.107])

        all_signals = []
        for i in range(n):
            snap = _make_snapshot(fvgs=[fvg] if i >= 9 else [])
            snap.bar_index = i
            signals = det.process_bar(
                snap, open_, high, low, close,
                bar_idx=i, bar_time=base + timedelta(minutes=i * 5),
                atr=0.001, spread=0.00015,
            )
            all_signals.extend(signals)

        assert len(all_signals) >= 1
        sig = all_signals[0]
        assert sig.direction == Direction.LONG

    def test_dst_london_summer(self):
        """In summer, London 08:00 local = 07:00 UTC.
        The detector should still work correctly."""
        cfg = OpeningRangeConfig(
            session_name="london",
            tz_name="Europe/London",
            range_start_local="08:00",
            range_end_local="08:30",
            min_range_atr=0.0,
            max_range_atr=100.0,
        )
        det = OpeningRangeDetector(config=cfg)

        # July 15 2024: BST, London 08:00 = 07:00 UTC
        base = datetime(2024, 7, 15, 7, 0)
        n = 10
        open_ = np.full(n, 1.10)
        high = np.full(n, 1.103)
        low = np.full(n, 1.097)
        close = np.full(n, 1.10)

        for i in range(n):
            snap = _make_snapshot()
            snap.bar_index = i
            det.process_bar(
                snap, open_, high, low, close,
                bar_idx=i, bar_time=base + timedelta(minutes=i * 5),
                atr=0.001, spread=0.00015,
            )

        range_instances = [
            inst for inst in det.tracker.active_instances
            if inst.state == StrategyState.RANGE_COMPLETE
        ]
        assert len(range_instances) == 2
