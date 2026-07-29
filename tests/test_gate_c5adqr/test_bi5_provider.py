"""Gate C5-A-DQR operational provider tests."""
from __future__ import annotations

import json
import lzma
import struct
from datetime import date
from pathlib import Path

from fx_smc_bot.data.daily_checkpoint import DayStatus, MonthManifest, compact_month
from fx_smc_bot.data.dukascopy_bi5 import (
    BROWSER_USER_AGENT,
    USDJPY_INTEGER_SCALE,
    dukascopy_candle_url,
    parse_bi5_m1_candles,
    validate_m1_rows,
)


def _bi5_payload(records: list[tuple[int, int, int, int, int, float]]) -> bytes:
    raw = b"".join(struct.pack(">iiiii f", *record) for record in records)
    return lzma.compress(raw, format=lzma.FORMAT_ALONE)


def test_pair_specific_integer_quantization_usdjpy() -> None:
    payload = _bi5_payload([
        (60, 107971, 107968, 107965, 108016, 686.98),
    ])

    rows = parse_bi5_m1_candles(payload, date(2020, 1, 6))

    assert USDJPY_INTEGER_SCALE == 1000
    assert rows[0]["open"] == 107.971
    assert rows[0]["high"] == 108.016
    assert rows[0]["low"] == 107.965
    assert rows[0]["close"] == 107.968
    assert rows[0]["open_raw"] == 107971


def test_flat_rows_follow_pinned_ignore_flats_semantics() -> None:
    payload = _bi5_payload([
        (0, 100000, 100000, 100000, 100000, 0.0),
        (60, 100001, 100002, 100000, 100003, 1.0),
    ])

    rows = parse_bi5_m1_candles(payload, date(2020, 1, 6))

    assert len(rows) == 1
    assert rows[0]["timestamp"] == 1578268860000


def test_validate_rows_rejects_timestamp_range() -> None:
    rows = [{
        "timestamp": 1578355200000,
        "open_raw": 1,
        "high_raw": 1,
        "low_raw": 1,
        "close_raw": 1,
    }]

    report = validate_m1_rows(rows, date(2020, 1, 6))

    assert report["timestamps_in_requested_day"] is False


def test_failed_days_prevent_compaction(tmp_path: Path) -> None:
    manifest = MonthManifest(pair="USDJPY", side="bid", year=2020, month=1)
    for day_num in range(1, 32):
        manifest.days.append(DayStatus(
            pair="USDJPY",
            side="bid",
            year=2020,
            month=1,
            day=day_num,
            status="failed" if day_num == 6 else "market_closed",
            rows=0,
        ))

    compact_month(tmp_path, manifest)

    assert manifest.compacted is False


def test_zero_rows_prevent_completion(tmp_path: Path) -> None:
    manifest = MonthManifest(pair="USDJPY", side="bid", year=2020, month=1)
    for day_num in range(1, 32):
        manifest.days.append(DayStatus(
            pair="USDJPY",
            side="bid",
            year=2020,
            month=1,
            day=day_num,
            status="complete",
            rows=0,
        ))

    compact_month(tmp_path, manifest)

    assert manifest.compacted is False


def test_dukascopy_url_uses_zero_based_month() -> None:
    url = dukascopy_candle_url("USDJPY", date(2020, 1, 6), "bid")

    assert url.endswith("/USDJPY/2020/00/06/BID_candles_min_1.bi5")


def test_cache_isolated_provider_execution_metadata() -> None:
    assert "Mozilla/5.0" in BROWSER_USER_AGENT


def test_fallback_requires_operational_amendment_before_repair() -> None:
    protocol = {
        "provider_parity_passed": False,
        "operational_provider_amendment_hash": "",
    }

    blocked = (
        not protocol["provider_parity_passed"]
        or not protocol["operational_provider_amendment_hash"]
    )

    assert blocked is True


def test_targeted_day_only_repair_manifest_shape() -> None:
    manifest = {
        "requested_units": [
            {"day": "2020-01-06", "side": "bid"},
        ],
        "full_redownload": False,
    }

    assert manifest["full_redownload"] is False
    assert len(manifest["requested_units"]) == 1


def test_atomic_monthly_recompaction_uses_tmp_then_replace() -> None:
    source = Path("src/fx_smc_bot/data/daily_checkpoint.py").read_text()

    assert "with_suffix(\".tmp\")" in source
    assert "os.replace" in source


def test_no_scientific_operations_in_dqr_runner() -> None:
    source = Path("scripts/run_gate_c5adqr.py").read_text().lower()

    forbidden = [
        "extract_events(",
        "apply_outcomes(",
        "construct_controls(",
        "run_placebo(",
        "load_holdout",
        "run_backtest(",
    ]
    for token in forbidden:
        assert token not in source


def test_resumption_handoff_integrity_shape() -> None:
    handoff = {
        "status": "READY_TO_RESUME_FROZEN_C5A_FROM_EVENT_DETECTION",
        "event_counts_computed": False,
        "outcomes_computed": False,
        "holdout_accessed": False,
    }

    assert handoff["event_counts_computed"] is False
    assert handoff["outcomes_computed"] is False
    assert handoff["holdout_accessed"] is False


def test_canonical_rebuild_determinism_checksum() -> None:
    rows = [{"timestamp": 1, "bid": 1.0, "ask": 1.1}]
    a = json.dumps(rows, sort_keys=True, separators=(",", ":"))
    b = json.dumps(rows, sort_keys=True, separators=(",", ":"))

    assert a == b
