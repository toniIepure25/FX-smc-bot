"""FX market calendar: session windows, weekends, holidays, and news events.

The FX spot market operates ~24/5 from Sunday 17:00 ET (22:00 UTC) to
Friday 17:00 ET (22:00 UTC).  This module provides deterministic
helpers for session classification, market-open checks, and
high-impact event windows used by feed health monitoring and
no-trade-window enforcement.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from enum import Enum
from typing import Sequence


# All internal logic is UTC.  ET offsets are baked in as constants.
_ET_OFFSET_HOURS = -5  # EST; DST not modeled — conservative
_FRIDAY = 4
_SUNDAY = 6
_SATURDAY = 5

# FX market close: Friday 22:00 UTC (17:00 ET)
_MARKET_CLOSE_UTC = time(22, 0)
# FX market open: Sunday 22:00 UTC (17:00 ET)
_MARKET_OPEN_UTC = time(22, 0)


class FxSession(str, Enum):
    SYDNEY = "sydney"
    TOKYO = "tokyo"
    LONDON = "london"
    NEW_YORK = "new_york"
    LONDON_NY_OVERLAP = "london_ny_overlap"
    OFF_HOURS = "off_hours"


@dataclass(slots=True, frozen=True)
class SessionWindow:
    name: FxSession
    open_utc: time
    close_utc: time


# Standard session boundaries (UTC)
FX_SESSIONS: list[SessionWindow] = [
    SessionWindow(FxSession.SYDNEY, time(21, 0), time(6, 0)),      # prev day 21:00 -> 06:00
    SessionWindow(FxSession.TOKYO, time(0, 0), time(9, 0)),
    SessionWindow(FxSession.LONDON, time(7, 0), time(16, 0)),
    SessionWindow(FxSession.NEW_YORK, time(12, 0), time(21, 0)),
    SessionWindow(FxSession.LONDON_NY_OVERLAP, time(12, 0), time(16, 0)),
]


@dataclass(slots=True, frozen=True)
class HighImpactEvent:
    """Scheduled macro event that may warrant a no-trade window."""
    name: str
    day_of_week: int          # 0=Mon .. 6=Sun
    week_of_month: int | None  # 1-based; None = every week
    hour_utc: int
    minute_utc: int = 0
    buffer_minutes_before: int = 30
    buffer_minutes_after: int = 30


# Recurring high-impact USD events (approximate schedule)
DEFAULT_HIGH_IMPACT_EVENTS: list[HighImpactEvent] = [
    HighImpactEvent("NFP", day_of_week=4, week_of_month=1, hour_utc=13, minute_utc=30,
                    buffer_minutes_before=60, buffer_minutes_after=60),
    HighImpactEvent("FOMC_Decision", day_of_week=2, week_of_month=None, hour_utc=19, minute_utc=0,
                    buffer_minutes_before=60, buffer_minutes_after=60),
    HighImpactEvent("CPI", day_of_week=2, week_of_month=2, hour_utc=13, minute_utc=30,
                    buffer_minutes_before=30, buffer_minutes_after=30),
]


# Annual holidays when FX markets are closed or illiquid
ANNUAL_HOLIDAYS: list[tuple[int, int]] = [
    (1, 1),   # New Year's Day
    (12, 25), # Christmas
]


def is_market_open(timestamp: datetime) -> bool:
    """True if the FX spot market is expected to be open at *timestamp* (UTC)."""
    wd = timestamp.weekday()
    t = timestamp.time()

    if wd == _SATURDAY:
        return False
    if wd == _SUNDAY:
        return t >= _MARKET_OPEN_UTC
    if wd == _FRIDAY:
        return t < _MARKET_CLOSE_UTC
    if _is_holiday(timestamp):
        return False
    return True


def next_market_open(timestamp: datetime) -> datetime:
    """Return the next expected market open after *timestamp* (UTC)."""
    dt = timestamp.replace(second=0, microsecond=0)
    for _ in range(10):
        if dt.weekday() == _FRIDAY and dt.time() >= _MARKET_CLOSE_UTC:
            # Jump to Sunday open
            days_ahead = 2
            dt = dt.replace(hour=22, minute=0) + timedelta(days=days_ahead)
            continue
        if dt.weekday() == _SATURDAY:
            days_ahead = 1
            dt = dt.replace(hour=22, minute=0) + timedelta(days=days_ahead)
            continue
        if dt.weekday() == _SUNDAY and dt.time() < _MARKET_OPEN_UTC:
            dt = dt.replace(hour=22, minute=0)
            return dt
        if _is_holiday(dt):
            dt = (dt + timedelta(days=1)).replace(hour=0, minute=0)
            continue
        if is_market_open(dt):
            return dt
        dt += timedelta(hours=1)
    return dt


def current_session(timestamp: datetime) -> FxSession:
    """Return the primary FX session active at *timestamp* (UTC)."""
    if not is_market_open(timestamp):
        return FxSession.OFF_HOURS

    t = timestamp.time()

    if time(12, 0) <= t < time(16, 0):
        return FxSession.LONDON_NY_OVERLAP
    if time(7, 0) <= t < time(16, 0):
        return FxSession.LONDON
    if time(12, 0) <= t < time(21, 0):
        return FxSession.NEW_YORK
    if time(0, 0) <= t < time(9, 0):
        return FxSession.TOKYO
    return FxSession.SYDNEY


def is_high_impact_window(
    timestamp: datetime,
    events: Sequence[HighImpactEvent] | None = None,
) -> bool:
    """True if *timestamp* falls within the buffer zone of any scheduled event."""
    for ev in (events or DEFAULT_HIGH_IMPACT_EVENTS):
        if ev.day_of_week != timestamp.weekday():
            continue
        if ev.week_of_month is not None:
            week = (timestamp.day - 1) // 7 + 1
            if week != ev.week_of_month:
                continue
        event_time = timestamp.replace(hour=ev.hour_utc, minute=ev.minute_utc, second=0, microsecond=0)
        window_start = event_time - timedelta(minutes=ev.buffer_minutes_before)
        window_end = event_time + timedelta(minutes=ev.buffer_minutes_after)
        if window_start <= timestamp <= window_end:
            return True
    return False


def expected_bar_interval(timeframe_minutes: int) -> timedelta:
    """Expected wall-clock interval between consecutive bars."""
    return timedelta(minutes=timeframe_minutes)


def _is_holiday(timestamp: datetime) -> bool:
    return (timestamp.month, timestamp.day) in ANNUAL_HOLIDAYS
