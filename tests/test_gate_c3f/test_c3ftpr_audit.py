from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from scripts.run_gate_c3ftpr_audit import (
    HourResult,
    TickRecord,
    aggregate_ticks_to_m1,
    classify_audit,
    compare_m1,
    quantize_canonical,
    selected_diagnostic_case,
)


def _hour(records: list[TickRecord]) -> HourResult:
    return HourResult(
        pair="EURUSD",
        hour=datetime(2015, 1, 19, tzinfo=UTC),
        records=records,
        cache_file="data/raw/test.bi5",
        cache_hit=False,
        bytes_read=100,
        sha256="abc",
        error=None,
    )


def test_selected_diagnostic_uses_first_window_and_first_pair() -> None:
    plan = {
        "windows": [
            {
                "year": 2015,
                "quarter": 1,
                "week_start": "2015-01-19",
                "week_end": "2015-01-24",
                "session": "london",
            },
            {
                "year": 2015,
                "quarter": 2,
                "week_start": "2015-04-06",
                "week_end": "2015-04-11",
                "session": "new_york",
            },
        ]
    }

    pair, window, index = selected_diagnostic_case(plan)

    assert pair == "EURUSD"
    assert index == 0
    assert window["week_start"] == "2015-01-19"


def test_tick_aggregation_preserves_open_high_low_close() -> None:
    records = [
        TickRecord(datetime(2015, 1, 19, 0, 0, 10, tzinfo=UTC), 100001, 100004, 1, 1, 0),
        TickRecord(datetime(2015, 1, 19, 0, 0, 20, tzinfo=UTC), 100003, 100006, 1, 1, 1),
        TickRecord(datetime(2015, 1, 19, 0, 0, 30, tzinfo=UTC), 100000, 100002, 1, 1, 2),
        TickRecord(datetime(2015, 1, 19, 0, 1, 0, tzinfo=UTC), 100010, 100012, 1, 1, 3),
    ]

    out = aggregate_ticks_to_m1("EURUSD", [_hour(records)])

    assert len(out) == 2
    first = out.iloc[0]
    assert first["bid_open"] == 100001
    assert first["bid_high"] == 100003
    assert first["bid_low"] == 100000
    assert first["bid_close"] == 100000
    assert first["ask_open"] == 100004
    assert first["ask_high"] == 100006
    assert first["ask_low"] == 100002
    assert first["ask_close"] == 100002


def test_quantize_canonical_to_integer_raw_points() -> None:
    df = pd.DataFrame({
        "timestamp": [pd.Timestamp("2015-01-19T00:00:00Z")],
        "bid_open": [1.00001],
        "bid_high": [1.00002],
        "bid_low": [1.0],
        "bid_close": [1.00001],
        "ask_open": [1.00003],
        "ask_high": [1.00004],
        "ask_low": [1.00002],
        "ask_close": [1.00003],
    })

    out = quantize_canonical("EURUSD", df)

    assert out.loc[0, "bid_open"] == 100001
    assert out.loc[0, "ask_high"] == 100004


def test_compare_m1_exact_match() -> None:
    row = {
        "timestamp": pd.Timestamp("2015-01-19T00:00:00Z"),
        "bid_open": 100001,
        "bid_high": 100003,
        "bid_low": 100000,
        "bid_close": 100002,
        "ask_open": 100004,
        "ask_high": 100006,
        "ask_low": 100002,
        "ask_close": 100005,
    }
    result = compare_m1(pd.DataFrame([row]), pd.DataFrame([row]))

    assert result["timestamp_agreement"] is True
    assert result["exact_ohlc_agreement"] is True
    assert result["compared_bars"] == 1


def test_compare_m1_empty_canonical_is_incomplete_not_ohlc_disagreement() -> None:
    row = {
        "timestamp": pd.Timestamp("2015-01-19T00:00:00Z"),
        "bid_open": 100001,
        "bid_high": 100001,
        "bid_low": 100001,
        "bid_close": 100001,
        "ask_open": 100004,
        "ask_high": 100004,
        "ask_low": 100004,
        "ask_close": 100004,
    }
    result = compare_m1(pd.DataFrame([row]), pd.DataFrame())

    assert result["exact_ohlc_agreement"] is True
    assert result["missing_in_canonical_count"] == 1


def test_audit_classification_order() -> None:
    exact = {"timestamp_agreement": True, "exact_ohlc_agreement": True}
    mismatch = {"timestamp_agreement": True, "exact_ohlc_agreement": False}
    missing_ts = {"timestamp_agreement": False, "exact_ohlc_agreement": True}
    incomplete = {
        "timestamp_agreement": False,
        "exact_ohlc_agreement": True,
        "missing_in_tick_count": 0,
        "missing_in_canonical_count": 1,
    }

    assert (
        classify_audit({"tick_count": 0, "download_error_count": 0}, [], exact)
        == "FAIL_DATA_ACCESS"
    )
    assert (
        classify_audit({"tick_count": 1, "download_error_count": 0}, ["missing"], exact)
        == "FAIL_INCOMPLETE_WINDOW"
    )
    assert (
        classify_audit({"tick_count": 1, "download_error_count": 0}, [], incomplete)
        == "FAIL_INCOMPLETE_WINDOW"
    )
    assert (
        classify_audit({"tick_count": 1, "download_error_count": 0}, [], missing_ts)
        == "FAIL_TIMESTAMP_ALIGNMENT"
    )
    assert (
        classify_audit({"tick_count": 1, "download_error_count": 0}, [], mismatch)
        == "FAIL_OHLC_DISAGREEMENT"
    )
    assert (
        classify_audit({"tick_count": 1, "download_error_count": 1}, [], exact)
        == "PASS_PROTOCOL_BOUNDED"
    )
    assert (
        classify_audit({"tick_count": 1, "download_error_count": 0}, [], exact)
        == "PASS_EXACT"
    )
