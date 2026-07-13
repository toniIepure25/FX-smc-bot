"""DST-aware session boundary computation.

Uses IANA time zones (via zoneinfo) so that session windows like
"08:00-08:30 Europe/London" automatically shift in UTC when DST
changes.  This replaces the fixed-UTC-offset approach for any
research that requires precise session alignment.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

_LONDON = ZoneInfo("Europe/London")
_NEW_YORK = ZoneInfo("America/New_York")
_UTC = ZoneInfo("UTC")


def local_time_to_utc(
    dt_date: datetime,
    local_time: time,
    tz: ZoneInfo,
) -> datetime:
    """Convert a local time on a given date to a UTC datetime.

    Handles DST transitions by letting zoneinfo resolve the offset.
    """
    local_dt = datetime(
        dt_date.year, dt_date.month, dt_date.day,
        local_time.hour, local_time.minute, local_time.second,
        tzinfo=tz,
    )
    return local_dt.astimezone(_UTC).replace(tzinfo=None)


def session_window_utc(
    dt_date: datetime,
    start_local: time,
    end_local: time,
    tz_name: str,
) -> tuple[datetime, datetime]:
    """Return (start_utc, end_utc) for a session window on a given date.

    Parameters
    ----------
    dt_date : date context (only year/month/day used)
    start_local : session start in local time
    end_local : session end in local time
    tz_name : IANA timezone string (e.g. "Europe/London")
    """
    tz = ZoneInfo(tz_name)
    start_utc = local_time_to_utc(dt_date, start_local, tz)
    end_utc = local_time_to_utc(dt_date, end_local, tz)
    if end_utc <= start_utc:
        end_utc += timedelta(days=1)
    return start_utc, end_utc


def london_session_utc(
    dt_date: datetime,
    start: time = time(8, 0),
    end: time = time(16, 30),
) -> tuple[datetime, datetime]:
    """London session boundaries in UTC, DST-aware."""
    return session_window_utc(dt_date, start, end, "Europe/London")


def new_york_session_utc(
    dt_date: datetime,
    start: time = time(8, 0),
    end: time = time(17, 0),
) -> tuple[datetime, datetime]:
    """New York session boundaries in UTC, DST-aware."""
    return session_window_utc(dt_date, start, end, "America/New_York")


def opening_range_utc(
    dt_date: datetime,
    start_local: time,
    end_local: time,
    tz_name: str,
) -> tuple[datetime, datetime]:
    """Opening range window in UTC, DST-aware.

    For example: 08:00-08:30 Europe/London shifts between
    08:00-08:30 UTC (summer) and 08:00-08:30 UTC (winter)
    in local terms, but the UTC values will be 07:00/07:30
    during BST and 08:00/08:30 during GMT.
    """
    return session_window_utc(dt_date, start_local, end_local, tz_name)


def fx_trading_day_boundaries_dst(
    ts: datetime,
) -> tuple[datetime, datetime]:
    """Return FX trading day boundaries using NY 17:00 local time.

    Unlike utils/time.trading_day_boundaries which uses fixed 21:00 UTC,
    this accounts for DST: NY 17:00 = 22:00 UTC in winter, 21:00 UTC in summer.
    """
    ny_date = ts.replace(tzinfo=_UTC).astimezone(_NEW_YORK)
    ny_pivot_time = time(17, 0)

    pivot_local = datetime(
        ny_date.year, ny_date.month, ny_date.day,
        ny_pivot_time.hour, ny_pivot_time.minute,
        tzinfo=_NEW_YORK,
    )
    pivot_utc = pivot_local.astimezone(_UTC).replace(tzinfo=None)

    if ts >= pivot_utc:
        return pivot_utc, pivot_utc + timedelta(days=1)
    pivot_prev = (pivot_local - timedelta(days=1)).astimezone(_UTC).replace(tzinfo=None)
    return pivot_prev, pivot_utc


def is_dst_transition_date(dt_date: datetime, tz_name: str) -> bool:
    """Check if the given date has a DST transition in the specified timezone."""
    tz = ZoneInfo(tz_name)
    day_start = datetime(dt_date.year, dt_date.month, dt_date.day, 0, 0, tzinfo=tz)
    day_end = datetime(dt_date.year, dt_date.month, dt_date.day, 23, 59, tzinfo=tz)
    return day_start.utcoffset() != day_end.utcoffset()
