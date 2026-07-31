from __future__ import annotations

from datetime import date, datetime

import pytest

from fx_smc_bot.research import rate_calendars as calendars


def test_registry_exposes_exact_named_calendars_and_currency_mapping() -> None:
    assert tuple(calendars.CALENDARS) == (
        "NEW_YORK_FED_BUSINESS_DAY",
        "TARGET2",
        "LONDON_BUSINESS_DAY",
        "RITS_BUSINESS_DAY",
        "TOKYO_BUSINESS_DAY",
        "BANK_OF_CANADA_ANNOUNCEMENT_CALENDAR",
        "CHF_CURRENCY_BUSINESS_DAY",
        "FX_TRADING_DAY",
    )
    assert calendars.CURRENCY_CALENDAR_IDS == {
        "USD": calendars.NEW_YORK_FED_BUSINESS_DAY,
        "EUR": calendars.TARGET2,
        "GBP": calendars.LONDON_BUSINESS_DAY,
        "AUD": calendars.RITS_BUSINESS_DAY,
        "JPY": calendars.TOKYO_BUSINESS_DAY,
        "CAD": calendars.BANK_OF_CANADA_ANNOUNCEMENT_CALENDAR,
        "CHF": calendars.CHF_CURRENCY_BUSINESS_DAY,
    }
    assert {item.version for item in calendars.CALENDARS.values()} == {
        "F0RPE2E_RATE_CALENDARS_V2"
    }


@pytest.mark.parametrize(
    ("calendar_id", "holiday"),
    [
        (calendars.NEW_YORK_FED_BUSINESS_DAY, date(2012, 7, 4)),
        (calendars.TARGET2, date(2012, 4, 6)),
        (calendars.LONDON_BUSINESS_DAY, date(2012, 4, 9)),
        (calendars.RITS_BUSINESS_DAY, date(2012, 1, 26)),
        (calendars.TOKYO_BUSINESS_DAY, date(2012, 5, 3)),
        (calendars.CHF_CURRENCY_BUSINESS_DAY, date(2012, 8, 1)),
        (calendars.FX_TRADING_DAY, date(2012, 12, 25)),
    ],
)
def test_named_calendars_apply_explicit_holiday_rules(calendar_id: str, holiday: date) -> None:
    definition = calendars.calendar_definition(calendar_id)
    assert not definition.is_open(holiday)
    assert not definition.is_open(date(2012, 7, 7))


def test_target_calendar_is_rule_based_not_observation_based() -> None:
    target = calendars.calendar_definition(calendars.TARGET2)
    assert target.is_open(date(2012, 4, 5))
    assert not target.is_open(date(2012, 4, 6))
    assert not target.is_open(date(2012, 4, 9))
    assert target.is_open(date(2012, 4, 10))


def test_new_year_observed_closure_can_fall_in_prior_calendar_year() -> None:
    fed = calendars.calendar_definition(calendars.NEW_YORK_FED_BUSINESS_DAY)
    assert not fed.is_open(date(2010, 12, 31))


def test_policy_announcement_calendar_requires_explicit_certified_dates() -> None:
    announcement = calendars.calendar_definition(
        calendars.BANK_OF_CANADA_ANNOUNCEMENT_CALENDAR
    )
    event = date(2012, 1, 17)
    assert announcement.requires_explicit_event_dates
    assert not announcement.is_open(event)
    assert announcement.is_open(event, event_dates=frozenset({event}))
    assert not announcement.is_open(
        event,
        event_dates=frozenset({event}),
        additional_closures=frozenset({event}),
    )


def test_bounded_enumeration_is_deterministic_and_rejects_reverse_interval() -> None:
    first = calendars.calendar_days(
        calendars.FX_TRADING_DAY, date(2012, 1, 2), date(2012, 1, 8)
    )
    second = calendars.calendar_days(
        calendars.FX_TRADING_DAY, date(2012, 1, 2), date(2012, 1, 8)
    )
    assert first == second == (
        date(2012, 1, 2),
        date(2012, 1, 3),
        date(2012, 1, 4),
        date(2012, 1, 5),
        date(2012, 1, 6),
    )
    with pytest.raises(ValueError, match="precedes"):
        calendars.calendar_days(
            calendars.FX_TRADING_DAY, date(2012, 1, 8), date(2012, 1, 2)
        )


def test_unknown_calendar_and_currency_fail_closed() -> None:
    with pytest.raises(ValueError, match="Unknown rate calendar"):
        calendars.calendar_definition("SYNTHETIC_UNKNOWN")
    with pytest.raises(ValueError, match="outside"):
        calendars.calendar_for_currency("XYZ")
    with pytest.raises(TypeError, match="must be a date"):
        calendars.calendar_definition(calendars.TARGET2).is_open(  # type: ignore[arg-type]
            datetime(2012, 1, 3)
        )


def test_london_exception_calendar_covers_authorized_one_off_holidays() -> None:
    london = calendars.calendar_definition(calendars.LONDON_BUSINESS_DAY)
    assert not london.is_open(date(2011, 4, 29))
    assert london.is_open(date(2012, 5, 28))
    assert not london.is_open(date(2012, 6, 4))
    assert not london.is_open(date(2012, 6, 5))
    assert london.is_open(date(2020, 5, 4))
    assert not london.is_open(date(2020, 5, 8))
    assert london.is_open(date(2022, 5, 30))
    assert not london.is_open(date(2022, 6, 2))
    assert not london.is_open(date(2022, 6, 3))
    assert not london.is_open(date(2022, 9, 19))


def test_rits_and_tokyo_critical_exceptions_are_explicit() -> None:
    rits = calendars.calendar_definition(calendars.RITS_BUSINESS_DAY)
    tokyo = calendars.calendar_definition(calendars.TOKYO_BUSINESS_DAY)
    assert not rits.is_open(date(2011, 4, 26))
    assert not rits.is_open(date(2022, 9, 22))
    assert not tokyo.is_open(date(2019, 5, 1))
    assert not tokyo.is_open(date(2019, 10, 22))
    assert not tokyo.is_open(date(2020, 7, 23))
    assert tokyo.is_open(date(2020, 7, 20))
    assert not tokyo.is_open(date(2021, 8, 9))


def test_calendars_reject_days_outside_authorized_interval() -> None:
    target = calendars.calendar_definition(calendars.TARGET2)
    with pytest.raises(ValueError, match="authorized 2010-2022 interval"):
        target.is_open(date(2009, 12, 31))
