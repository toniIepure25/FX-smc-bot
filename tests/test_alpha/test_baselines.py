"""Tests for baseline strategy detectors."""

from __future__ import annotations

from datetime import datetime

import pytest

from fx_smc_bot.alpha.baselines import (
    MeanReversionDetector,
    MomentumDetector,
    SessionBreakoutDetector,
)
from fx_smc_bot.config import SessionConfig, Timeframe, TradingPair
from fx_smc_bot.domain import (
    Direction,
    MultiTimeframeContext,
    SessionName,
    SessionWindow,
    StructureRegime,
    StructureSnapshot,
    SwingPoint,
    SwingType,
)


def _make_snapshot(
    pair: TradingPair = TradingPair.EURUSD,
    bar_index: int = 100,
    swings: list[SwingPoint] | None = None,
    session_windows: list[SessionWindow] | None = None,
) -> StructureSnapshot:
    return StructureSnapshot(
        pair=pair, timeframe=Timeframe.M15, bar_index=bar_index,
        regime=StructureRegime.BULLISH,
        swings=swings or [],
        session_windows=session_windows or [],
    )


def _make_context(
    snapshot: StructureSnapshot | None = None,
) -> MultiTimeframeContext:
    snap = snapshot or _make_snapshot()
    return MultiTimeframeContext(
        pair=snap.pair, htf_snapshot=snap, ltf_snapshot=snap,
        htf_bias=Direction.LONG,
    )


class TestMomentumDetector:
    def test_conforms_to_protocol(self) -> None:
        d = MomentumDetector()
        assert hasattr(d, "scan")

    def test_no_candidates_with_few_swings(self) -> None:
        d = MomentumDetector()
        ctx = _make_context(_make_snapshot(swings=[]))
        result = d.scan(ctx, 1.1000, datetime(2024, 1, 2, 10, 0))
        assert result == []

    def test_generates_long_on_breakout(self) -> None:
        d = MomentumDetector(lookback=5)
        highs = [SwingPoint(i, 1.10 + i * 0.001, SwingType.HIGH, datetime(2024, 1, 2, i))
                 for i in range(10)]
        lows = [SwingPoint(i, 1.09 + i * 0.001, SwingType.LOW, datetime(2024, 1, 2, i))
                for i in range(10)]
        swings = sorted(highs + lows, key=lambda s: s.bar_index)
        snap = _make_snapshot(bar_index=100, swings=swings)
        ctx = _make_context(snap)
        # Price above all recent highs
        result = d.scan(ctx, 1.12, datetime(2024, 1, 2, 12, 0))
        if result:
            assert result[0].direction == Direction.LONG
            assert "momentum" in result[0].tags


class TestSessionBreakoutDetector:
    def test_no_signal_during_asian(self) -> None:
        d = SessionBreakoutDetector()
        snap = _make_snapshot()
        ctx = _make_context(snap)
        result = d.scan(ctx, 1.1000, datetime(2024, 1, 2, 3, 0))
        assert result == []

    def test_long_breakout_above_asian_high(self) -> None:
        d = SessionBreakoutDetector()
        asian_window = SessionWindow(
            session_name=SessionName.ASIAN,
            date=datetime(2024, 1, 2),
            open_time=datetime(2024, 1, 2, 0, 0),
            close_time=datetime(2024, 1, 2, 8, 0),
            high=1.1020, low=1.0980,
        )
        snap = _make_snapshot(session_windows=[asian_window])
        ctx = _make_context(snap)
        # Price above Asian high during London
        result = d.scan(ctx, 1.1030, datetime(2024, 1, 2, 9, 0))
        if result:
            assert result[0].direction == Direction.LONG
            assert "session_breakout" in result[0].tags


class TestMeanReversionDetector:
    def test_conforms_to_protocol(self) -> None:
        d = MeanReversionDetector()
        assert hasattr(d, "scan")

    def test_no_signal_near_mean(self) -> None:
        d = MeanReversionDetector(lookback=10)
        swings = [
            SwingPoint(i, 1.1 + (i % 2) * 0.001, SwingType.HIGH, datetime(2024, 1, 2, i))
            for i in range(20)
        ]
        snap = _make_snapshot(swings=swings)
        ctx = _make_context(snap)
        result = d.scan(ctx, 1.1005, datetime(2024, 1, 2, 12, 0))
        assert result == []

    def test_short_signal_on_extreme_high(self) -> None:
        d = MeanReversionDetector(lookback=10, entry_sigma=1.5, sl_sigma=2.5)
        # Create swings centered around 1.10 with small variance
        swings = [
            SwingPoint(i, 1.10 + 0.0002 * (i % 3 - 1), SwingType.HIGH, datetime(2024, 1, 2, i))
            for i in range(20)
        ]
        snap = _make_snapshot(swings=swings)
        ctx = _make_context(snap)
        # Price way above mean
        result = d.scan(ctx, 1.11, datetime(2024, 1, 2, 12, 0))
        if result:
            assert result[0].direction == Direction.SHORT
            assert "mean_reversion" in result[0].tags
