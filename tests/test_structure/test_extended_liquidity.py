"""Tests for session/daily/weekly liquidity level detection."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from fx_smc_bot.config import SessionConfig, Timeframe, TradingPair
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.domain import (
    LiquidityLevel,
    LiquidityLevelType,
    MarketBar,
    SessionName,
    SessionWindow,
)
from fx_smc_bot.structure.liquidity import (
    detect_daily_levels,
    detect_session_levels,
    detect_sweeps,
    detect_weekly_levels,
)


def _make_multi_day_series(
    n_days: int = 5,
    bars_per_day: int = 96,
    tf_minutes: int = 15,
) -> BarSeries:
    """Create M15 bars spanning multiple days starting Monday 00:00 UTC."""
    start = datetime(2024, 1, 8, 0, 0)  # Monday
    delta = timedelta(minutes=tf_minutes)
    bars: list[MarketBar] = []
    rng = np.random.default_rng(42)
    price = 1.1000

    for i in range(n_days * bars_per_day):
        ts = start + delta * i
        if ts.weekday() >= 5:
            continue
        move = rng.normal(0, 0.0005)
        close = price + move
        high = max(price, close) + abs(rng.normal(0, 0.0003))
        low = min(price, close) - abs(rng.normal(0, 0.0003))
        bars.append(MarketBar(
            pair=TradingPair.EURUSD, timeframe=Timeframe.M15,
            timestamp=ts, open=round(price, 5), high=round(high, 5),
            low=round(low, 5), close=round(close, 5),
            bar_index=len(bars), spread=0.00015,
        ))
        price = close

    return BarSeries.from_bars(bars)


class TestSessionLevels:

    def test_completed_session_creates_levels(self):
        """A completed session window should produce HIGH and LOW levels."""
        windows = [
            SessionWindow(
                session_name=SessionName.ASIAN,
                date=datetime(2024, 1, 8),
                open_time=datetime(2024, 1, 8, 0, 0),
                close_time=datetime(2024, 1, 8, 8, 0),
                high=1.1050, low=1.0950,
                high_index=10, low_index=20,
            ),
        ]
        levels = detect_session_levels(windows, current_bar_index=30)
        assert len(levels) == 2
        types = {lv.level_type for lv in levels}
        assert LiquidityLevelType.SESSION_HIGH in types
        assert LiquidityLevelType.SESSION_LOW in types

    def test_in_progress_session_not_available(self):
        """A session still in progress should NOT create levels."""
        windows = [
            SessionWindow(
                session_name=SessionName.LONDON,
                date=datetime(2024, 1, 8),
                open_time=datetime(2024, 1, 8, 7, 0),
                close_time=datetime(2024, 1, 8, 16, 0),
                high=1.1050, low=1.0950,
                high_index=30, low_index=40,
            ),
        ]
        levels = detect_session_levels(windows, current_bar_index=35)
        assert len(levels) == 0

    def test_session_level_formation_time_is_close(self):
        """Session level's formation_time should be the session close time."""
        close_time = datetime(2024, 1, 8, 8, 0)
        windows = [
            SessionWindow(
                session_name=SessionName.ASIAN,
                date=datetime(2024, 1, 8),
                open_time=datetime(2024, 1, 8, 0, 0),
                close_time=close_time,
                high=1.1050, low=1.0950,
                high_index=5, low_index=10,
            ),
        ]
        levels = detect_session_levels(windows, current_bar_index=20)
        for lv in levels:
            assert lv.formation_time == close_time


class TestDailyLevels:

    def test_prior_day_levels_created(self):
        series = _make_multi_day_series(n_days=3)
        current_idx = len(series) - 1
        levels = detect_daily_levels(
            series.high, series.low, series.timestamps, current_idx,
        )
        day_high_count = sum(
            1 for lv in levels
            if lv.level_type == LiquidityLevelType.PRIOR_DAY_HIGH
        )
        day_low_count = sum(
            1 for lv in levels
            if lv.level_type == LiquidityLevelType.PRIOR_DAY_LOW
        )
        assert day_high_count >= 1
        assert day_low_count >= 1

    def test_current_day_not_included(self):
        """Levels from the current (incomplete) day must not appear."""
        series = _make_multi_day_series(n_days=2)
        mid_day2 = len(series) // 2
        levels = detect_daily_levels(
            series.high, series.low, series.timestamps, mid_day2,
        )
        for lv in levels:
            assert lv.formation_index < mid_day2


class TestWeeklyLevels:

    def test_prior_week_levels(self):
        series = _make_multi_day_series(n_days=12)
        current_idx = len(series) - 1
        levels = detect_weekly_levels(
            series.high, series.low, series.timestamps, current_idx,
        )
        week_high = sum(
            1 for lv in levels
            if lv.level_type == LiquidityLevelType.PRIOR_WEEK_HIGH
        )
        assert week_high >= 1


class TestSweepWithExtendedLevels:

    def test_sweep_session_high(self):
        """A session high level that gets wicked through should be swept."""
        level = LiquidityLevel(
            price=1.1050,
            level_type=LiquidityLevelType.SESSION_HIGH,
            touch_count=1,
            formation_index=5,
            formation_time=datetime(2024, 1, 8, 8, 0),
        )
        high = np.array([1.10, 1.10, 1.10, 1.10, 1.10, 1.10, 1.106, 1.10])
        low = np.array([1.09, 1.09, 1.09, 1.09, 1.09, 1.09, 1.098, 1.09])
        close = np.array([1.10, 1.10, 1.10, 1.10, 1.10, 1.10, 1.100, 1.10])
        ts = np.array([
            np.datetime64("2024-01-08T00:00") + np.timedelta64(i * 15, "m")
            for i in range(8)
        ])

        result = detect_sweeps([level], high, low, close, ts)
        assert len(result) == 1
        assert result[0].swept is True
        assert result[0].sweep_index == 6

    def test_sweep_prior_day_low(self):
        """A prior day low that gets wicked below should be swept."""
        level = LiquidityLevel(
            price=1.0950,
            level_type=LiquidityLevelType.PRIOR_DAY_LOW,
            touch_count=1,
            formation_index=3,
            formation_time=datetime(2024, 1, 8, 21, 0),
        )
        high = np.array([1.10, 1.10, 1.10, 1.10, 1.10, 1.10, 1.10])
        low = np.array([1.09, 1.09, 1.09, 1.096, 1.09, 1.094, 1.09])
        close = np.array([1.10, 1.10, 1.10, 1.096, 1.10, 1.096, 1.10])
        ts = np.array([
            np.datetime64("2024-01-09T00:00") + np.timedelta64(i * 15, "m")
            for i in range(7)
        ])

        result = detect_sweeps([level], high, low, close, ts)
        assert len(result) == 1
        assert result[0].swept is True
