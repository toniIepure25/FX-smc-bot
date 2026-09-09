"""Tests for the corrected FX weekly-session calendar and the monthly certifier."""

from __future__ import annotations

from datetime import date

from fx_smc_bot.research.v3 import fx_calendar as fc
from fx_smc_bot.research.v3 import monthly_certify as mc


# --- FX weekly calendar contract ---
def test_saturday_is_only_full_closure() -> None:
    assert fc.is_market_closed_calendar(date(2014, 6, 14))       # Saturday
    assert not fc.is_market_closed_calendar(date(2014, 6, 8))    # Sunday (partial trading)
    assert not fc.is_market_closed_calendar(date(2014, 6, 13))   # Friday (partial trading)
    assert fc.is_trading_date(date(2014, 6, 8))                  # Sunday IS a trading date
    assert not fc.is_trading_date(date(2014, 6, 14))             # Saturday is not


def test_session_classification() -> None:
    assert fc.classify_session(date(2014, 6, 8)) == fc.PARTIAL_SUNDAY_OPEN
    assert fc.classify_session(date(2014, 6, 9)) == fc.FULL_SESSION
    assert fc.classify_session(date(2014, 6, 13)) == fc.PARTIAL_FRIDAY_CLOSE
    assert fc.classify_session(date(2014, 6, 14)) == fc.CLOSED_SATURDAY


def test_dst_aware_open_close() -> None:
    # Summer (EDT): Sunday opens 21:00 UTC; winter (EST): 22:00 UTC.
    summer = fc.session_window_utc(date(2014, 6, 8))
    winter = fc.session_window_utc(date(2014, 1, 5))
    assert summer is not None and winter is not None
    assert summer[0].hour == 21
    assert winter[0].hour == 22
    # Friday close mirrors the open hour.
    assert fc.session_window_utc(date(2014, 6, 13))[1].hour == 21  # type: ignore[index]
    assert fc.session_window_utc(date(2014, 1, 10))[1].hour == 22  # type: ignore[index]


def test_partial_days_not_1440() -> None:
    assert fc.expected_minutes(date(2014, 6, 9)) == 1440          # Mon full
    assert 0 < fc.expected_minutes(date(2014, 6, 8)) < 1440       # Sunday partial
    assert 0 < fc.expected_minutes(date(2014, 6, 13)) < 1440      # Friday partial
    assert fc.expected_minutes(date(2014, 6, 14)) == 0           # Saturday closed


def test_sunday_included_in_trading_dates() -> None:
    days = list(fc.trading_dates(date(2014, 6, 8), date(2014, 6, 14)))
    weekdays = {d.strftime("%a") for d in days}
    assert "Sun" in weekdays and "Sat" not in weekdays


def test_session_hours_partial_vs_full() -> None:
    assert fc.session_hours(date(2014, 6, 9)) == list(range(24))         # Mon full
    assert fc.session_hours(date(2014, 6, 14)) == []                     # Saturday closed
    sun = fc.session_hours(date(2014, 6, 8))                             # EDT open 21:00 UTC
    assert sun and min(sun) == 21 and max(sun) == 23
    fri = fc.session_hours(date(2014, 6, 13))                            # EDT close 21:00 UTC
    assert fri[0] == 0 and max(fri) == 20


# --- monthly certifier ---
def _row(ts: int, px: float) -> dict[str, float | int]:
    return {"timestamp": ts, "open": px, "high": px + 0.0001, "low": px - 0.0001, "close": px}


def _complete_month_rows(year: int, month: int) -> dict[str, list[dict[str, float | int]]]:
    rows: dict[str, list[dict[str, float | int]]] = {}
    ts = 1_000_000
    for d in mc.month_trading_dates(year, month):
        day_rows = []
        for _ in range(3):
            day_rows.append(_row(ts, 1.1000))
            ts += 60000  # globally monotonic across the whole month
        rows[d.isoformat()] = day_rows
    return rows


def test_month_certified_when_complete() -> None:
    rows = _complete_month_rows(2014, 6)
    transport = {d: "NATIVE_M1" for d in rows}
    cert = mc.certify_month(instrument="EURUSD", year=2014, month=6, side="bid",
                            rows_by_date=rows, transport_by_date=transport,
                            fallback_by_date={}, decimals=5)
    assert cert["status"] == mc.CERTIFIED
    assert cert["missing_dates"] == []
    assert cert["transport_mix"] == ["NATIVE_M1"]


def test_month_incomplete_when_missing_trading_date() -> None:
    rows = _complete_month_rows(2014, 6)
    rows.pop(sorted(rows)[10])  # drop one trading date -> gap (not from silence, a real gap)
    cert = mc.certify_month(instrument="EURUSD", year=2014, month=6, side="bid",
                            rows_by_date=rows, transport_by_date={d: "NATIVE_M1" for d in rows},
                            fallback_by_date={}, decimals=5)
    assert cert["status"] == mc.INCOMPLETE
    assert len(cert["missing_dates"]) == 1


def test_month_integrity_failure_on_bad_ohlc() -> None:
    rows = _complete_month_rows(2014, 6)
    first = sorted(rows)[0]
    rows[first][0]["high"] = 0.0  # high < low -> OHLC violation
    cert = mc.certify_month(instrument="EURUSD", year=2014, month=6, side="bid",
                            rows_by_date=rows, transport_by_date={d: "NATIVE_M1" for d in rows},
                            fallback_by_date={}, decimals=5)
    assert cert["status"] == mc.INTEGRITY_FAILURE


def test_global_digest_deterministic() -> None:
    rows = _complete_month_rows(2014, 6)
    cert = mc.certify_month(instrument="EURUSD", year=2014, month=6, side="bid",
                            rows_by_date=rows, transport_by_date={d: "NATIVE_M1" for d in rows},
                            fallback_by_date={}, decimals=5)
    d1 = mc.global_data_freeze_digest([cert])
    d2 = mc.global_data_freeze_digest([cert])
    assert d1["global_digest"] == d2["global_digest"]
    assert d1["certified_partitions"] == 1


# --- prospectively excluded dates (frozen TERMINAL_DATA_ABSENT rule) ---
def test_month_certified_when_missing_date_prospectively_excluded() -> None:
    rows = _complete_month_rows(2014, 6)
    dropped = sorted(rows)[10]
    rows.pop(dropped)
    cert = mc.certify_month(instrument="EURUSD", year=2014, month=6, side="bid",
                            rows_by_date=rows, transport_by_date={d: "NATIVE_M1" for d in rows},
                            fallback_by_date={}, decimals=5,
                            excluded_dates={dropped: "confirmed_no_market_observations_native_and_tick"})
    assert cert["status"] == mc.CERTIFIED
    assert cert["missing_dates"] == []
    assert cert["excluded_dates"] == {dropped: "confirmed_no_market_observations_native_and_tick"}
    assert cert["excluded_date_count"] == 1
    # required = present + excluded (identity)
    assert cert["required_trading_dates"] == cert["present_dates"] + cert["excluded_date_count"]


def test_month_still_incomplete_when_missing_date_not_excluded() -> None:
    rows = _complete_month_rows(2014, 6)
    dropped = sorted(rows)[10]
    other = sorted(rows)[5]
    rows.pop(dropped)
    rows.pop(other)
    cert = mc.certify_month(instrument="EURUSD", year=2014, month=6, side="bid",
                            rows_by_date=rows, transport_by_date={d: "NATIVE_M1" for d in rows},
                            fallback_by_date={}, decimals=5,
                            excluded_dates={other: "confirmed_no_market_observations_native_and_tick"})
    # excluding one absent date does not cover the other genuinely missing one
    assert cert["status"] == mc.INCOMPLETE
    assert cert["missing_dates"] == [dropped]


def test_present_and_excluded_is_a_contradiction() -> None:
    rows = _complete_month_rows(2014, 6)
    d = sorted(rows)[10]
    try:
        mc.certify_month(instrument="EURUSD", year=2014, month=6, side="bid",
                         rows_by_date=rows, transport_by_date={d: "NATIVE_M1" for d in rows},
                         fallback_by_date={}, decimals=5,
                         excluded_dates={d: "confirmed_no_market_observations_native_and_tick"})
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_digest_distinguishes_day_classes() -> None:
    rows = _complete_month_rows(2014, 6)
    dropped = sorted(rows)[10]
    rows.pop(dropped)
    cert = mc.certify_month(instrument="EURUSD", year=2014, month=6, side="bid",
                            rows_by_date=rows, transport_by_date={d: "NATIVE_M1" for d in rows},
                            fallback_by_date={}, decimals=5,
                            excluded_dates={dropped: "confirmed_no_market_observations_native_and_tick"})
    # a second partition with a genuinely unresolved (missing, not excluded) date
    rows2 = _complete_month_rows(2014, 6)
    unresolved = sorted(rows2)[3]
    rows2.pop(unresolved)
    cert2 = mc.certify_month(instrument="EURUSD", year=2014, month=6, side="ask",
                             rows_by_date=rows2,
                             transport_by_date={d: "NATIVE_M1" for d in rows2},
                             fallback_by_date={}, decimals=5)
    d = mc.global_data_freeze_digest([cert, cert2])
    assert d["artifact_id"] == "V3_GLOBAL_DATA_FREEZE_DIGEST_V2"
    assert d["certified_partitions"] == 1
    classes = d["partition_day_class_counts"]
    n = len(mc.month_trading_dates(2014, 6))  # Saturdays excluded by the frozen calendar
    # cert: n-1 present + 1 excluded; cert2: n-1 present + 1 unresolved.
    assert classes["certified_days"] == 2 * (n - 1)
    assert classes["excluded_days"] == 1
    assert classes["unresolved_days"] == 1
    # determinism + order independence
    d2 = mc.global_data_freeze_digest([cert2, cert])
    assert d["global_digest"] == d2["global_digest"]
