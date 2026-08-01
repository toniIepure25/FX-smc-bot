"""Explicit rate-publication and FX trading calendars for Gate F0-RP-E2E.

Calendar membership is derived from named rules, never from the presence or
absence of rate observations.  The event-driven Bank of Canada calendar is
the sole exception to rule generation: callers must supply the certified
announcement dates pinned by their dataset freeze.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Final

NEW_YORK_FED_BUSINESS_DAY: Final = "NEW_YORK_FED_BUSINESS_DAY"
TARGET2: Final = "TARGET2"
LONDON_BUSINESS_DAY: Final = "LONDON_BUSINESS_DAY"
RITS_BUSINESS_DAY: Final = "RITS_BUSINESS_DAY"
TOKYO_BUSINESS_DAY: Final = "TOKYO_BUSINESS_DAY"
BANK_OF_CANADA_ANNOUNCEMENT_CALENDAR: Final = "BANK_OF_CANADA_ANNOUNCEMENT_CALENDAR"
CHF_CURRENCY_BUSINESS_DAY: Final = "CHF_CURRENCY_BUSINESS_DAY"
FX_TRADING_DAY: Final = "FX_TRADING_DAY"

CALENDAR_VERSION: Final = "F0RPE2E_RATE_CALENDARS_V2"
_WEEKEND: Final = frozenset({5, 6})
SUPPORTED_START: Final = date(2010, 1, 1)
SUPPORTED_END: Final = date(2022, 12, 31)

_LONDON_ADDITIONAL_HOLIDAYS: Final = {
    2011: frozenset({date(2011, 4, 29)}),
    2012: frozenset({date(2012, 6, 4), date(2012, 6, 5)}),
    2020: frozenset({date(2020, 5, 8)}),
    2022: frozenset({date(2022, 6, 2), date(2022, 6, 3), date(2022, 9, 19)}),
}
_LONDON_REPLACED_HOLIDAYS: Final = {
    2012: frozenset({date(2012, 5, 28)}),
    2020: frozenset({date(2020, 5, 4)}),
    2022: frozenset({date(2022, 5, 30)}),
}
_RITS_ADDITIONAL_HOLIDAYS: Final = {
    2011: frozenset({date(2011, 4, 26)}),
    2022: frozenset({date(2022, 9, 22)}),
}


@dataclass(frozen=True)
class CalendarDefinition:
    """Immutable identity and deterministic rules for one named calendar."""

    calendar_id: str
    timezone: str
    calendar_kind: str
    rule_names: tuple[str, ...]
    requires_explicit_event_dates: bool = False
    version: str = CALENDAR_VERSION

    def is_open(
        self,
        day: date,
        *,
        event_dates: frozenset[date] = frozenset(),
        additional_closures: frozenset[date] = frozenset(),
    ) -> bool:
        """Return calendar membership using only explicit rules and inputs."""
        if type(day) is not date:
            raise TypeError("Calendar day must be a date")
        if not SUPPORTED_START <= day <= SUPPORTED_END:
            raise ValueError("Calendar day is outside the authorized 2010-2022 interval")
        if self.requires_explicit_event_dates:
            return day in event_dates and day not in additional_closures
        return (
            day.weekday() not in _WEEKEND
            and day not in _holidays(self.calendar_id, day.year)
            and day not in additional_closures
        )


CALENDARS: Final[dict[str, CalendarDefinition]] = {
    NEW_YORK_FED_BUSINESS_DAY: CalendarDefinition(
        NEW_YORK_FED_BUSINESS_DAY,
        "America/New_York",
        "BUSINESS_DAY",
        ("US_FEDERAL_HOLIDAYS", "SATURDAY_SUNDAY_CLOSED"),
    ),
    TARGET2: CalendarDefinition(
        TARGET2,
        "Europe/Brussels",
        "BUSINESS_DAY",
        ("TARGET_CLOSING_DAYS", "SATURDAY_SUNDAY_CLOSED"),
    ),
    LONDON_BUSINESS_DAY: CalendarDefinition(
        LONDON_BUSINESS_DAY,
        "Europe/London",
        "BUSINESS_DAY",
        ("ENGLAND_WALES_BANK_HOLIDAYS", "SATURDAY_SUNDAY_CLOSED"),
    ),
    RITS_BUSINESS_DAY: CalendarDefinition(
        RITS_BUSINESS_DAY,
        "Australia/Sydney",
        "BUSINESS_DAY",
        ("RITS_NSW_SETTLEMENT_HOLIDAYS", "SATURDAY_SUNDAY_CLOSED"),
    ),
    TOKYO_BUSINESS_DAY: CalendarDefinition(
        TOKYO_BUSINESS_DAY,
        "Asia/Tokyo",
        "BUSINESS_DAY",
        ("JAPAN_BANK_HOLIDAYS", "SATURDAY_SUNDAY_CLOSED"),
    ),
    BANK_OF_CANADA_ANNOUNCEMENT_CALENDAR: CalendarDefinition(
        BANK_OF_CANADA_ANNOUNCEMENT_CALENDAR,
        "America/Toronto",
        "EVENT",
        ("CERTIFIED_POLICY_ANNOUNCEMENT_DATES",),
        requires_explicit_event_dates=True,
    ),
    CHF_CURRENCY_BUSINESS_DAY: CalendarDefinition(
        CHF_CURRENCY_BUSINESS_DAY,
        "Europe/Zurich",
        "BUSINESS_DAY",
        ("ZURICH_CURRENCY_HOLIDAYS", "SATURDAY_SUNDAY_CLOSED"),
    ),
    FX_TRADING_DAY: CalendarDefinition(
        FX_TRADING_DAY,
        "America/New_York",
        "TRADING_DAY",
        ("GLOBAL_FX_FULL_CLOSURES", "SATURDAY_SUNDAY_CLOSED"),
    ),
}

CURRENCY_CALENDAR_IDS: Final = {
    "USD": NEW_YORK_FED_BUSINESS_DAY,
    "EUR": TARGET2,
    "GBP": LONDON_BUSINESS_DAY,
    "AUD": RITS_BUSINESS_DAY,
    "JPY": TOKYO_BUSINESS_DAY,
    "CAD": BANK_OF_CANADA_ANNOUNCEMENT_CALENDAR,
    "CHF": CHF_CURRENCY_BUSINESS_DAY,
}


def calendar_definition(calendar_id: str) -> CalendarDefinition:
    """Resolve an exact named calendar, failing closed for unknown names."""
    try:
        return CALENDARS[calendar_id]
    except KeyError as exc:
        raise ValueError(f"Unknown rate calendar: {calendar_id}") from exc


def calendar_for_currency(currency: str) -> CalendarDefinition:
    """Return the frozen official calendar assigned to an authorized currency."""
    try:
        return CALENDARS[CURRENCY_CALENDAR_IDS[currency]]
    except KeyError as exc:
        raise ValueError("Currency is outside the amended rate-calendar registry") from exc


def calendar_days(
    calendar_id: str,
    start: date,
    end: date,
    *,
    event_dates: frozenset[date] = frozenset(),
    additional_closures: frozenset[date] = frozenset(),
) -> tuple[date, ...]:
    """Enumerate named-calendar days over an explicitly bounded interval."""
    if type(start) is not date or type(end) is not date:
        raise TypeError("Calendar interval boundaries must be dates")
    if end < start:
        raise ValueError("Calendar interval end precedes start")
    definition = calendar_definition(calendar_id)
    span = (end - start).days
    return tuple(
        day
        for offset in range(span + 1)
        if definition.is_open(
            day := start + timedelta(days=offset),
            event_dates=event_dates,
            additional_closures=additional_closures,
        )
    )


def _holidays(calendar_id: str, year: int) -> frozenset[date]:
    if calendar_id == NEW_YORK_FED_BUSINESS_DAY:
        return _new_york_fed_holidays(year)
    if calendar_id == TARGET2:
        easter = _easter_sunday(year)
        return frozenset(
            {
                date(year, 1, 1),
                easter - timedelta(days=2),
                easter + timedelta(days=1),
                date(year, 5, 1),
                date(year, 12, 25),
                date(year, 12, 26),
            }
        )
    if calendar_id == LONDON_BUSINESS_DAY:
        return _london_holidays(year)
    if calendar_id == RITS_BUSINESS_DAY:
        return _rits_holidays(year)
    if calendar_id == TOKYO_BUSINESS_DAY:
        return _tokyo_holidays(year)
    if calendar_id == CHF_CURRENCY_BUSINESS_DAY:
        return _zurich_holidays(year)
    if calendar_id == FX_TRADING_DAY:
        return frozenset({date(year, 1, 1), date(year, 12, 25)})
    if calendar_id == BANK_OF_CANADA_ANNOUNCEMENT_CALENDAR:
        return frozenset()
    raise ValueError(f"Unknown rate calendar: {calendar_id}")


def _new_york_fed_holidays(year: int) -> frozenset[date]:
    holidays = {
        _observed_us(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _last_weekday(year, 5, 0),
        _observed_us(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 10, 0, 2),
        _observed_us(date(year, 11, 11)),
        _nth_weekday(year, 11, 3, 4),
        _observed_us(date(year, 12, 25)),
    }
    if year >= 2022:
        holidays.add(_observed_us(date(year, 6, 19)))
    next_new_year = _observed_us(date(year + 1, 1, 1))
    if next_new_year.year == year:
        holidays.add(next_new_year)
    return frozenset(holidays)


def _london_holidays(year: int) -> frozenset[date]:
    easter = _easter_sunday(year)
    holidays = {
        _next_weekday(date(year, 1, 1)),
        easter - timedelta(days=2),
        easter + timedelta(days=1),
        _nth_weekday(year, 5, 0, 1),
        _last_weekday(year, 5, 0),
        _last_weekday(year, 8, 0),
    }
    holidays.update(_paired_weekday_substitutes(date(year, 12, 25), date(year, 12, 26)))
    holidays.difference_update(_LONDON_REPLACED_HOLIDAYS.get(year, frozenset()))
    holidays.update(_LONDON_ADDITIONAL_HOLIDAYS.get(year, frozenset()))
    return frozenset(holidays)


def _rits_holidays(year: int) -> frozenset[date]:
    easter = _easter_sunday(year)
    holidays = {
        _next_weekday(date(year, 1, 1)),
        _next_weekday(date(year, 1, 26)),
        easter - timedelta(days=2),
        easter + timedelta(days=1),
        _next_weekday(date(year, 4, 25)),
        _nth_weekday(year, 6, 0, 2),
        _nth_weekday(year, 8, 0, 1),
        _nth_weekday(year, 10, 0, 1),
    }
    holidays.update(_paired_weekday_substitutes(date(year, 12, 25), date(year, 12, 26)))
    holidays.update(_RITS_ADDITIONAL_HOLIDAYS.get(year, frozenset()))
    return frozenset(holidays)


def _tokyo_holidays(year: int) -> frozenset[date]:
    holidays = {
        date(year, 1, 1),
        date(year, 1, 2),
        date(year, 1, 3),
        _nth_weekday(year, 1, 0, 2),
        date(year, 2, 11),
        date(year, 4, 29),
        date(year, 5, 3),
        date(year, 5, 4),
        date(year, 5, 5),
        _nth_weekday(year, 9, 0, 3),
        date(year, 11, 3),
        date(year, 11, 23),
    }
    if year == 2020:
        holidays.update({date(2020, 7, 23), date(2020, 7, 24), date(2020, 8, 10)})
    elif year == 2021:
        holidays.update({date(2021, 7, 22), date(2021, 7, 23), date(2021, 8, 8)})
    else:
        holidays.update(
            {_nth_weekday(year, 7, 0, 3), _nth_weekday(year, 10, 0, 2)}
        )
        if year >= 2016:
            holidays.add(date(year, 8, 11))
    if 1989 <= year <= 2018:
        holidays.add(date(year, 12, 23))
    if year >= 2020:
        holidays.add(date(year, 2, 23))
    if year == 2019:
        holidays.update(
            {
                date(2019, 4, 30),
                date(2019, 5, 1),
                date(2019, 5, 2),
                date(2019, 10, 22),
            }
        )
    holidays.add(date(year, 3, _japan_vernal_equinox_day(year)))
    holidays.add(date(year, 9, _japan_autumn_equinox_day(year)))
    for holiday in sorted(tuple(holidays)):
        if holiday.weekday() == 6:
            substitute = holiday + timedelta(days=1)
            while substitute in holidays:
                substitute += timedelta(days=1)
            holidays.add(substitute)
    for ordinal in range(date(year, 1, 2).toordinal(), date(year, 12, 31).toordinal()):
        candidate = date.fromordinal(ordinal)
        if (
            candidate.weekday() not in _WEEKEND
            and candidate - timedelta(days=1) in holidays
            and candidate + timedelta(days=1) in holidays
        ):
            holidays.add(candidate)
    return frozenset(holidays)


def _zurich_holidays(year: int) -> frozenset[date]:
    easter = _easter_sunday(year)
    return frozenset(
        {
            date(year, 1, 1),
            date(year, 1, 2),
            easter - timedelta(days=2),
            easter + timedelta(days=1),
            date(year, 5, 1),
            easter + timedelta(days=39),
            easter + timedelta(days=50),
            date(year, 8, 1),
            date(year, 12, 25),
            date(year, 12, 26),
        }
    )


def _nth_weekday(year: int, month: int, weekday: int, occurrence: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7 + 7 * (occurrence - 1)
    return first + timedelta(days=offset)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    next_month = date(year + (month == 12), month % 12 + 1, 1)
    last = next_month - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed_us(holiday: date) -> date:
    if holiday.weekday() == 5:
        return holiday - timedelta(days=1)
    if holiday.weekday() == 6:
        return holiday + timedelta(days=1)
    return holiday


def _next_weekday(holiday: date) -> date:
    while holiday.weekday() in _WEEKEND:
        holiday += timedelta(days=1)
    return holiday


def _paired_weekday_substitutes(first: date, second: date) -> frozenset[date]:
    holidays = {first, second}
    for holiday in (first, second):
        if holiday.weekday() in _WEEKEND:
            substitute = holiday + timedelta(days=1)
            while substitute.weekday() in _WEEKEND or substitute in holidays:
                substitute += timedelta(days=1)
            holidays.add(substitute)
    return frozenset(holidays)


def _easter_sunday(year: int) -> date:
    """Gregorian Easter using the anonymous computus algorithm."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    month_offset = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * month_offset) // 451
    month = (h + month_offset - 7 * m + 114) // 31
    day = (h + month_offset - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def _japan_vernal_equinox_day(year: int) -> int:
    return int(20.8431 + 0.242194 * (year - 1980) - (year - 1980) // 4)


def _japan_autumn_equinox_day(year: int) -> int:
    return int(23.2488 + 0.242194 * (year - 1980) - (year - 1980) // 4)


assert tuple(CALENDARS) == (
    NEW_YORK_FED_BUSINESS_DAY,
    TARGET2,
    LONDON_BUSINESS_DAY,
    RITS_BUSINESS_DAY,
    TOKYO_BUSINESS_DAY,
    BANK_OF_CANADA_ANNOUNCEMENT_CALENDAR,
    CHF_CURRENCY_BUSINESS_DAY,
    FX_TRADING_DAY,
)
assert set(CURRENCY_CALENDAR_IDS) == {"USD", "EUR", "GBP", "AUD", "JPY", "CAD", "CHF"}
