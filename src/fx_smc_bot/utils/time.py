"""Time and session utilities for FX markets."""

from __future__ import annotations

from datetime import datetime, time, timedelta

from fx_smc_bot.config import SessionConfig
from fx_smc_bot.domain import SessionName


def time_in_range(t: time, start: time, end: time) -> bool:
    """Check if *t* falls within [start, end), handling midnight wrap."""
    if start <= end:
        return start <= t < end
    # Wraps midnight (e.g. 22:00 -> 06:00)
    return t >= start or t < end


def classify_session(ts: datetime, cfg: SessionConfig) -> SessionName | None:
    """Return the most specific session for a UTC timestamp, or None if outside all."""
    t = ts.time()
    if time_in_range(t, cfg.london_ny_overlap.start, cfg.london_ny_overlap.end):
        return SessionName.LONDON_NY_OVERLAP
    if time_in_range(t, cfg.london.start, cfg.london.end):
        return SessionName.LONDON
    if time_in_range(t, cfg.new_york.start, cfg.new_york.end):
        return SessionName.NEW_YORK
    if time_in_range(t, cfg.asian.start, cfg.asian.end):
        return SessionName.ASIAN
    return None


def is_weekend(ts: datetime) -> bool:
    """FX market is closed Saturday 00:00 UTC through Sunday ~21:00 UTC.

    Simplified: treat Saturday and Sunday as weekend.
    """
    return ts.weekday() >= 5


def trading_day_boundaries(ts: datetime) -> tuple[datetime, datetime]:
    """Return (start, end) of the FX trading day containing *ts*.

    FX convention: day starts at 17:00 New York (22:00 UTC in winter, 21:00 summer).
    Simplified here to 21:00 UTC.
    """
    pivot = ts.replace(hour=21, minute=0, second=0, microsecond=0)
    if ts.hour >= 21:
        return pivot, pivot + timedelta(days=1)
    return pivot - timedelta(days=1), pivot


def trading_week_boundaries(ts: datetime) -> tuple[datetime, datetime]:
    """Return (start, end) of the FX trading week containing *ts*.

    Week starts Sunday 21:00 UTC and ends Friday 21:00 UTC.
    """
    day_start, _ = trading_day_boundaries(ts)
    weekday = day_start.weekday()
    # Sunday = 6 in Python weekday()
    days_since_sunday = (weekday + 1) % 7
    week_start = day_start - timedelta(days=days_since_sunday)
    week_end = week_start + timedelta(days=5)
    return week_start, week_end
