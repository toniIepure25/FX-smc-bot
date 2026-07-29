"""Tests for DST-aware session boundary computation."""

from __future__ import annotations

from datetime import datetime, time

import pytest

from fx_smc_bot.data.timezone import (
    fx_trading_day_boundaries_dst,
    is_dst_transition_date,
    london_session_utc,
    new_york_session_utc,
    opening_range_utc,
    session_window_utc,
)


class TestSessionWindowUTC:

    def test_london_winter(self):
        """In winter (GMT), London 08:00 = 08:00 UTC."""
        date = datetime(2024, 1, 15)
        start, end = session_window_utc(
            date, time(8, 0), time(8, 30), "Europe/London",
        )
        assert start.hour == 8
        assert start.minute == 0
        assert end.hour == 8
        assert end.minute == 30

    def test_london_summer(self):
        """In summer (BST = UTC+1), London 08:00 = 07:00 UTC."""
        date = datetime(2024, 7, 15)
        start, end = session_window_utc(
            date, time(8, 0), time(8, 30), "Europe/London",
        )
        assert start.hour == 7
        assert start.minute == 0
        assert end.hour == 7
        assert end.minute == 30

    def test_new_york_winter(self):
        """In winter (EST = UTC-5), NY 08:00 = 13:00 UTC."""
        date = datetime(2024, 1, 15)
        start, end = session_window_utc(
            date, time(8, 0), time(8, 30), "America/New_York",
        )
        assert start.hour == 13
        assert start.minute == 0
        assert end.hour == 13
        assert end.minute == 30

    def test_new_york_summer(self):
        """In summer (EDT = UTC-4), NY 08:00 = 12:00 UTC."""
        date = datetime(2024, 7, 15)
        start, end = session_window_utc(
            date, time(8, 0), time(8, 30), "America/New_York",
        )
        assert start.hour == 12
        assert start.minute == 0
        assert end.hour == 12
        assert end.minute == 30


class TestLondonSession:

    def test_default_london_winter(self):
        date = datetime(2024, 1, 15)
        start, end = london_session_utc(date)
        assert start.hour == 8
        assert end.hour == 16
        assert end.minute == 30

    def test_default_london_summer(self):
        date = datetime(2024, 7, 15)
        start, end = london_session_utc(date)
        assert start.hour == 7
        assert end.hour == 15
        assert end.minute == 30


class TestNewYorkSession:

    def test_default_ny_winter(self):
        date = datetime(2024, 1, 15)
        start, end = new_york_session_utc(date)
        assert start.hour == 13
        assert end.hour == 22

    def test_default_ny_summer(self):
        date = datetime(2024, 7, 15)
        start, end = new_york_session_utc(date)
        assert start.hour == 12
        assert end.hour == 21


class TestOpeningRange:

    def test_london_opening_range_winter(self):
        date = datetime(2024, 1, 15)
        start, end = opening_range_utc(
            date, time(8, 0), time(8, 30), "Europe/London",
        )
        assert start == datetime(2024, 1, 15, 8, 0)
        assert end == datetime(2024, 1, 15, 8, 30)

    def test_london_opening_range_summer(self):
        date = datetime(2024, 7, 15)
        start, end = opening_range_utc(
            date, time(8, 0), time(8, 30), "Europe/London",
        )
        assert start == datetime(2024, 7, 15, 7, 0)
        assert end == datetime(2024, 7, 15, 7, 30)


class TestFXTradingDay:

    def test_winter_pivot(self):
        """NY 17:00 EST = 22:00 UTC in winter."""
        ts = datetime(2024, 1, 15, 23, 0)
        start, end = fx_trading_day_boundaries_dst(ts)
        assert start.hour == 22

    def test_summer_pivot(self):
        """NY 17:00 EDT = 21:00 UTC in summer."""
        ts = datetime(2024, 7, 15, 22, 0)
        start, end = fx_trading_day_boundaries_dst(ts)
        assert start.hour == 21


class TestDSTTransition:

    def test_spring_forward(self):
        """US spring forward: second Sunday in March 2024 = March 10."""
        assert is_dst_transition_date(datetime(2024, 3, 10), "America/New_York")

    def test_normal_day(self):
        assert not is_dst_transition_date(datetime(2024, 6, 15), "America/New_York")

    def test_uk_spring_forward(self):
        """UK clocks change last Sunday in March 2024 = March 31."""
        assert is_dst_transition_date(datetime(2024, 3, 31), "Europe/London")
