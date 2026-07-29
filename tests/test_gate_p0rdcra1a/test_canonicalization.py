from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from fx_smc_bot.config import Timeframe
from fx_smc_bot.data.bidask_resampling import resample_bidask

SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "run_gate_p0rdcra1a.py"


@pytest.fixture(scope="module")
def gate_module():
    spec = importlib.util.spec_from_file_location(
        "run_gate_p0rdcra1a_canonicalization_tests",
        SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _rows(*, ask: bool = False) -> list[dict[str, float | int]]:
    offset = 0.0002 if ask else 0.0
    start_ms = 1_577_836_800_000
    rows = []
    for index in range(10):
        price = 1.1000 + index * 0.0001 + offset
        rows.append(
            {
                "timestamp": start_ms + index * 60_000,
                "open": price,
                "high": price + 0.0001,
                "low": price - 0.0001,
                "close": price + 0.00005,
            }
        )
    return rows


def test_m1_to_m5_semantics_and_hash_are_deterministic(gate_module) -> None:
    first = gate_module._canonical_series_from_raw_rows(
        "EURUSD",
        _rows(),
        _rows(ask=True),
    )
    second = gate_module._canonical_series_from_raw_rows(
        "EURUSD",
        _rows(),
        _rows(ask=True),
    )

    assert first.timeframe == Timeframe.M1
    assert gate_module._series_semantic_sha256(first) == (
        gate_module._series_semantic_sha256(second)
    )
    m5 = resample_bidask(first, Timeframe.M5)
    assert len(m5) == 2
    assert m5.bid_open[0] == first.bid_open[0]
    assert m5.bid_high[0] == max(first.bid_high[:5])
    assert m5.bid_low[0] == min(first.bid_low[:5])
    assert m5.bid_close[0] == first.bid_close[4]
    assert m5.ask_open[0] == first.ask_open[0]
    assert m5.ask_close[0] == first.ask_close[4]
    assert (m5.ask_open > m5.bid_open).all()


def test_canonical_source_rejects_duplicates_and_side_mismatch(gate_module) -> None:
    bid = _rows()
    bid.append(dict(bid[-1]))
    with pytest.raises(ValueError, match="duplicate"):
        gate_module._canonical_series_from_raw_rows("EURUSD", bid, _rows(ask=True))

    with pytest.raises(ValueError, match="timestamp mismatch"):
        gate_module._canonical_series_from_raw_rows(
            "EURUSD",
            _rows()[:-1],
            _rows(ask=True),
        )


def _certified_partition_records() -> list[dict[str, str | int]]:
    return [
        {
            "instrument": instrument,
            "year": year,
            "month": month,
            "status": "CERTIFIED",
        }
        for instrument in ("EURUSD", "GBPUSD")
        for year in range(2015, 2023)
        for month in range(1, 13)
    ]


def test_candidate_certification_requires_all_authorized_partitions(gate_module) -> None:
    report = gate_module._candidate_level_certification(_certified_partition_records())

    assert report["status"] == "PASS"
    assert report["candidate_count"] == 4
    assert report["all_four_candidates_fully_certified"] is True
    assert report["missing_required_partitions"] == 0
    for candidate in report["candidates"]:
        assert candidate["required_instruments"] == ["EURUSD", "GBPUSD"]
        assert candidate["excluded_optional_diagnostics"] == ["USDJPY"]
        assert candidate["status"] == "FULLY_CERTIFIED"
        assert all(window["status"] == "FULLY_CERTIFIED" for window in candidate["windows"])

    incomplete = _certified_partition_records()[:-1]
    failed = gate_module._candidate_level_certification(incomplete)
    assert failed["status"] == "FAIL"
    assert failed["all_four_candidates_fully_certified"] is False
    assert failed["missing_required_partitions"] > 0


def test_provider_closed_reconciliation_requires_both_instruments(gate_module) -> None:
    records = []
    for instrument in ("EURUSD", "GBPUSD"):
        records.append(
            {
                "instrument": instrument,
                "year": 2019,
                "month": 1,
                "session_coverage": {
                    "london": {
                        "missing_dates": ["2019-01-01"],
                        "missing_days": 1,
                        "eligible_days": 22,
                        "expected_m5_buckets": 792,
                        "available_m5_buckets": 756,
                        "coverage_ratio": 0.95454545,
                        "provider_closed_observed_days": 0,
                    },
                    "new_york": {
                        "missing_dates": [],
                        "missing_days": 0,
                        "eligible_days": 22,
                        "expected_m5_buckets": 792,
                        "available_m5_buckets": 792,
                        "coverage_ratio": 1.0,
                        "provider_closed_observed_days": 0,
                    },
                },
            }
        )

    assert gate_module._reconcile_cross_instrument_provider_closures(records) == 2
    for item in records:
        london = item["session_coverage"]["london"]
        assert london["missing_days"] == 0
        assert london["provider_closed_observed_days"] == 1
        assert london["provider_closed_cross_instrument_dates"] == ["2019-01-01"]

    records[1]["session_coverage"]["london"]["missing_dates"] = []
    records[1]["session_coverage"]["london"]["missing_days"] = 0
    records[0]["session_coverage"]["london"]["missing_dates"] = ["2019-01-02"]
    records[0]["session_coverage"]["london"]["missing_days"] = 1
    assert gate_module._reconcile_cross_instrument_provider_closures(records) == 0
    assert records[0]["session_coverage"]["london"]["missing_days"] == 1


def test_frozen_dataset_metadata_hashes_and_scope(gate_module) -> None:
    result_dir = SCRIPT_PATH.parents[1] / "results" / "gate_p0rdcra1a"
    manifest = gate_module.load_json(result_dir / "canonical_partition_manifest.json")
    freeze = gate_module.load_json(result_dir / "permitted_dataset_freeze.json")

    manifest_hash = manifest.pop("manifest_hash")
    assert gate_module.canonical_json_sha256(manifest) == manifest_hash
    freeze_hash = freeze.pop("dataset_freeze_hash")
    assert gate_module.canonical_json_sha256(freeze) == freeze_hash
    assert freeze["dataset_freeze_id"] == (
        "FX_SMC_STRATEGY_ALPHA_PERMITTED_2015_2022_V2"
    )
    assert freeze["instruments"] == ["EURUSD", "GBPUSD"]
    assert freeze["end"] == "2022-12-31"
    assert freeze["economic_outcomes_accessed"] is False
    assert freeze["sealed_holdout_accessed"] is False
    assert manifest["partition_count"] == 192
    assert all(item["three_run_deterministic"] for item in manifest["partitions"])
