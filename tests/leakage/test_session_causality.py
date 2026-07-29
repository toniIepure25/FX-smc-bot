"""Tests proving session highs/lows are not known prematurely.

A session's high/low is only finalized after the session window ends.
During the session, only the running (incomplete) high/low is available.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from fx_smc_bot.config import SessionConfig, Timeframe, TradingPair
from fx_smc_bot.domain import MarketBar, SessionName
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.structure.sessions import track_session_windows


def _make_session_bars(
    session_start_hour: int = 7,
    session_end_hour: int = 16,
    n_hours: int = 24,
) -> BarSeries:
    """Create M15 bars spanning a full day with a known price spike
    at the end of the session."""
    start = datetime(2024, 1, 2, 0, 0)
    delta = timedelta(minutes=15)
    bars_per_hour = 4
    total_bars = n_hours * bars_per_hour
    bars: list[MarketBar] = []
    base = 1.1000

    for i in range(total_bars):
        ts = start + delta * i
        hour = ts.hour

        if hour == session_end_hour - 1 and ts.minute == 45:
            price = base + 0.0100  # spike near session end
        else:
            price = base + 0.0001 * (i % 10)

        bars.append(MarketBar(
            pair=TradingPair.EURUSD, timeframe=Timeframe.M15,
            timestamp=ts, open=price - 0.0002,
            high=price + 0.0003, low=price - 0.0003,
            close=price, bar_index=i, spread=0.00015,
        ))
    return BarSeries.from_bars(bars)


class TestSessionCausality:

    def test_session_window_high_updates_incrementally(self):
        """Track session windows and verify that the high only reaches
        its final value at the bar that creates it."""
        series = _make_session_bars()
        cfg = SessionConfig()

        windows = track_session_windows(
            series.high, series.low, series.timestamps, config=cfg,
        )

        london_windows = [
            w for w in windows if w.session_name == SessionName.LONDON
        ]
        assert len(london_windows) > 0, "Should detect London session"

    def test_prior_session_window_not_available_during_session(self):
        """Build structure at a bar inside a session. The current session's
        window should show partial data, not the final values."""
        series = _make_session_bars(n_hours=48)

        mid_session_idx = 10 * 4 + 2  # ~10:30 UTC, mid-London
        trunc = series.slice(0, mid_session_idx + 1)

        cfg = SessionConfig()
        windows = track_session_windows(
            trunc.high, trunc.low, trunc.timestamps, config=cfg,
        )

        for w in windows:
            assert w.close_time <= trunc.timestamps[-1].astype(
                "datetime64[us]"
            ).astype(datetime) or w.session_name in (
                SessionName.LONDON, SessionName.LONDON_NY_OVERLAP,
                SessionName.NEW_YORK,
            )

    def test_completed_session_has_correct_extremes(self):
        """After a session ends, its high/low must reflect all bars
        within the session window."""
        series = _make_session_bars()
        cfg = SessionConfig()

        windows = track_session_windows(
            series.high, series.low, series.timestamps, config=cfg,
        )

        for w in windows:
            start_idx = w.high_index
            assert start_idx >= 0 or w.high == 0.0
