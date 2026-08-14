"""Deterministic FX weekly-session calendar contract (America/New_York, DST-aware).

The FX week opens Sunday 17:00 America/New_York and closes Friday 17:00 America/New_York, and
is continuous Monday-Thursday. Expressed in UTC calendar days this means:

* Saturday .............. fully closed (the only non-trading weekday-type);
* Sunday ................ PARTIAL -- opens ~21:00/22:00 UTC (17:00 ET, DST-dependent);
* Monday-Thursday ....... FULL trading days;
* Friday ................ PARTIAL -- closes ~21:00/22:00 UTC (17:00 ET, DST-dependent).

Therefore a UTC date is a trading date iff its weekday is not Saturday. Sunday-open and
Friday-close partial-day row counts are LEGITIMATE; callers must not assume 1440 M1 rows on a
trading date. Genuine market closure is decided ONLY by this deterministic contract -- never
inferred from an HTTP 404/timeout/503 or any provider silence.

DST boundaries are handled by converting 17:00 local America/New_York to UTC via zoneinfo, so
the open/close UTC instant is correct across EST/EDT transitions.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fx_smc_bot.research.v3._hashing import canonical_hash

NY = ZoneInfo("America/New_York")
WEEK_OPEN_LOCAL_HOUR = 17   # Sunday 17:00 ET
WEEK_CLOSE_LOCAL_HOUR = 17  # Friday 17:00 ET

SATURDAY = 5
SUNDAY = 6
FRIDAY = 4

# Session classifications
CLOSED_SATURDAY = "CLOSED_SATURDAY"
PARTIAL_SUNDAY_OPEN = "PARTIAL_SUNDAY_OPEN"
FULL_SESSION = "FULL_SESSION"
PARTIAL_FRIDAY_CLOSE = "PARTIAL_FRIDAY_CLOSE"


def _local_1700_utc(d: date) -> datetime:
    """The UTC instant of 17:00 America/New_York on calendar date ``d`` (DST-correct)."""

    local = datetime(d.year, d.month, d.day, WEEK_OPEN_LOCAL_HOUR, 0, tzinfo=NY)
    return local.astimezone(timezone.utc)


def is_trading_date(d: date) -> bool:
    """True iff the UTC date contains any open FX minute (i.e. weekday is not Saturday)."""

    return d.weekday() != SATURDAY


def is_market_closed_calendar(d: date) -> bool:
    """Deterministic full-closure rule: only Saturday. Never inferred from provider silence."""

    return d.weekday() == SATURDAY


def classify_session(d: date) -> str:
    wd = d.weekday()
    if wd == SATURDAY:
        return CLOSED_SATURDAY
    if wd == SUNDAY:
        return PARTIAL_SUNDAY_OPEN
    if wd == FRIDAY:
        return PARTIAL_FRIDAY_CLOSE
    return FULL_SESSION


def session_window_utc(d: date) -> tuple[datetime, datetime] | None:
    """UTC [start, end) window covered by this date's trading portion (None if closed)."""

    wd = d.weekday()
    day_start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    next_day = day_start + timedelta(days=1)
    if wd == SATURDAY:
        return None
    if wd == SUNDAY:
        return (_local_1700_utc(d), next_day)               # evening open -> midnight
    if wd == FRIDAY:
        return (day_start, _local_1700_utc(d))              # midnight -> 17:00 ET close
    return (day_start, next_day)                            # Mon-Thu full


def expected_minutes(d: date) -> int:
    """Approximate expected M1 minutes for the trading portion (metadata; not enforced)."""

    win = session_window_utc(d)
    if win is None:
        return 0
    start, end = win
    return int((end - start).total_seconds() // 60)


def trading_dates(start: date, end: date):
    d = start
    one = timedelta(days=1)
    while d <= end:
        if is_trading_date(d):
            yield d
        d += one


def session_hours(d: date) -> list[int]:
    """UTC hours whose [h:00, h:59] overlap the FX session window for ``d`` (empty if closed)."""

    win = session_window_utc(d)
    if win is None:
        return []
    start, end = win
    day = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    hours: list[int] = []
    for h in range(24):
        hstart = day + timedelta(hours=h)
        if hstart < end and (hstart + timedelta(hours=1)) > start:
            hours.append(h)
    return hours


def fx_calendar_payload() -> dict[str, Any]:
    return {
        "artifact_id": "V3_FX_WEEKLY_CALENDAR_CONTRACT_V1",
        "timezone": "America/New_York",
        "week_open_local": f"Sunday {WEEK_OPEN_LOCAL_HOUR:02d}:00 ET",
        "week_close_local": f"Friday {WEEK_CLOSE_LOCAL_HOUR:02d}:00 ET",
        "rule": "trading date iff weekday != Saturday; Sunday partial (evening open), "
                "Mon-Thu full, Friday partial (evening close); DST-aware via zoneinfo.",
        "closure_determination": "ONLY the deterministic calendar; never from HTTP 404/"
                                 "timeout/503 or provider silence.",
        "partial_day_row_counts_legitimate": True,
        "do_not_assume_1440": True,
        "session_classes": [CLOSED_SATURDAY, PARTIAL_SUNDAY_OPEN, FULL_SESSION,
                            PARTIAL_FRIDAY_CLOSE],
    }


def fx_calendar_hash() -> str:
    return canonical_hash(fx_calendar_payload())
