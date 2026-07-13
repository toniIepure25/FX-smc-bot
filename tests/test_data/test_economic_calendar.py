"""Tests for economic calendar adapter."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from fx_smc_bot.data.economic_calendar import EconomicCalendar, EconomicEvent


def _make_test_csv(tmp_path, events=None):
    if events is None:
        events = [
            {"timestamp": "2024-01-05 13:30:00", "currency": "USD",
             "event_name": "Non-Farm Payrolls", "impact": "high",
             "actual": 216.0, "forecast": 175.0, "previous": 199.0},
            {"timestamp": "2024-01-05 15:00:00", "currency": "USD",
             "event_name": "ISM Services PMI", "impact": "high"},
            {"timestamp": "2024-01-08 10:00:00", "currency": "EUR",
             "event_name": "Retail Sales", "impact": "medium"},
            {"timestamp": "2024-01-10 13:30:00", "currency": "USD",
             "event_name": "CPI", "impact": "high"},
        ]
    df = pd.DataFrame(events)
    path = tmp_path / "calendar.csv"
    df.to_csv(path, index=False)
    return path


class TestEconomicCalendar:

    def test_load_csv(self, tmp_path):
        path = _make_test_csv(tmp_path)
        cal = EconomicCalendar.from_csv(path)
        assert len(cal.events) == 4

    def test_events_sorted_by_time(self, tmp_path):
        path = _make_test_csv(tmp_path)
        cal = EconomicCalendar.from_csv(path)
        for i in range(len(cal.events) - 1):
            assert cal.events[i].timestamp <= cal.events[i + 1].timestamp

    def test_events_in_window(self, tmp_path):
        path = _make_test_csv(tmp_path)
        cal = EconomicCalendar.from_csv(path)
        events = cal.events_in_window(
            datetime(2024, 1, 5, 13, 0),
            datetime(2024, 1, 5, 16, 0),
            min_impact="high",
        )
        assert len(events) == 2

    def test_currency_filter(self, tmp_path):
        path = _make_test_csv(tmp_path)
        cal = EconomicCalendar.from_csv(path)
        events = cal.events_in_window(
            datetime(2024, 1, 1),
            datetime(2024, 1, 31),
            currencies=["EUR"],
            min_impact="medium",
        )
        assert len(events) == 1
        assert events[0].currency == "EUR"

    def test_is_high_impact_window(self, tmp_path):
        path = _make_test_csv(tmp_path)
        cal = EconomicCalendar.from_csv(path)

        assert cal.is_high_impact_window(
            datetime(2024, 1, 5, 13, 25), minutes_before=15, minutes_after=15,
        )
        assert not cal.is_high_impact_window(
            datetime(2024, 1, 6, 10, 0), minutes_before=15, minutes_after=15,
        )

    def test_high_impact_windows(self, tmp_path):
        path = _make_test_csv(tmp_path)
        cal = EconomicCalendar.from_csv(path)
        windows = cal.high_impact_windows(
            datetime(2024, 1, 5, 0, 0),
            datetime(2024, 1, 5, 23, 59),
            minutes_before=10,
            minutes_after=10,
        )
        assert len(windows) == 2

    def test_parquet_roundtrip(self, tmp_path):
        csv_path = _make_test_csv(tmp_path)
        cal = EconomicCalendar.from_csv(csv_path)

        parquet_path = tmp_path / "calendar.parquet"
        df = pd.DataFrame([{
            "timestamp": ev.timestamp,
            "currency": ev.currency,
            "event_name": ev.event_name,
            "impact": ev.impact,
        } for ev in cal.events])
        df.to_parquet(parquet_path)

        cal2 = EconomicCalendar.from_parquet(parquet_path)
        assert len(cal2.events) == len(cal.events)

    def test_missing_columns_raises(self, tmp_path):
        df = pd.DataFrame({"timestamp": ["2024-01-01"], "currency": ["USD"]})
        path = tmp_path / "bad.csv"
        df.to_csv(path, index=False)
        with pytest.raises(ValueError, match="Missing columns"):
            EconomicCalendar.from_csv(path)
