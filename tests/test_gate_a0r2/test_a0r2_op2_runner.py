"""A0R2-OP2 durable operational runner tests."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from fx_smc_bot.data.daily_checkpoint import DayStatus, MonthManifest, save_month_manifest
from scripts import run_gate_a0r2 as runner


def _one_part() -> runner.Partition:
    return runner.Partition("EURUSD", 2010, 1, "bid")


def test_failed_terminal_survives_manifest_refresh() -> None:
    part = _one_part()
    manifest = MonthManifest(part.pair, part.side, part.year, part.month)
    manifest.compacted = True
    manifest.compacted_rows = 10
    persisted = {
        "pair": part.pair,
        "year": part.year,
        "month": part.month,
        "side": part.side,
        "state": "FAILED_TERMINAL",
        "attempts": 5,
        "outer_failure_attempts": 5,
        "terminal_reason": "RETRY_ATTEMPTS_EXHAUSTED",
        "error_fingerprint": "abc",
    }
    result = runner.reconcile_partition_state(persisted, manifest)
    assert result["state"] == "FAILED_TERMINAL"
    assert result["attempts"] == 5
    assert result["terminal_reason"] == "RETRY_ATTEMPTS_EXHAUSTED"
    assert result["error_fingerprint"] == "abc"


def test_certified_survives_failed_manifest_refresh() -> None:
    part = _one_part()
    manifest = MonthManifest(part.pair, part.side, part.year, part.month)
    manifest.days = [DayStatus(part.pair, part.side, part.year, part.month, 1, "failed")]
    result = runner.reconcile_partition_state(
        {
            "pair": part.pair,
            "year": part.year,
            "month": part.month,
            "side": part.side,
            "state": "CERTIFIED",
        },
        manifest,
    )
    assert result["state"] == "CERTIFIED"


def test_attempt_count_survives_restart_from_history(
    tmp_path: Path, monkeypatch
) -> None:
    part = _one_part()
    monkeypatch.setattr(runner, "partition_queue", lambda *args, **kwargs: [part])
    runner.append_event(tmp_path, {"partition": part.key, "attempts": 3})
    state = runner.refresh_state_from_manifests(tmp_path)
    assert state["partitions"][part.key]["attempts"] == 3


def test_attempt_five_becomes_terminal(tmp_path: Path, monkeypatch) -> None:
    part = _one_part()
    monkeypatch.setattr(runner, "partition_queue", lambda *args, **kwargs: [part])
    state = {
        "gate_id": runner.GATE_ID,
        "queue_order": "test",
        "total_partitions": 1,
        "partitions": {
            part.key: {
                "pair": part.pair,
                "year": part.year,
                "month": part.month,
                "side": part.side,
                "state": "FAILED_RETRYABLE",
                "attempts": 5,
                "outer_failure_attempts": 5,
            }
        },
    }
    runner.save_state(tmp_path, state)
    refreshed = runner.refresh_state_from_manifests(tmp_path)
    item = refreshed["partitions"][part.key]
    assert item["state"] == "FAILED_TERMINAL"
    assert item["terminal_reason"] == "RETRY_ATTEMPTS_EXHAUSTED"


def test_native_partial_progress_does_not_terminalize_at_legacy_five(
    tmp_path: Path, monkeypatch
) -> None:
    part = _one_part()
    monkeypatch.setattr(runner, "partition_queue", lambda *args, **kwargs: [part])
    manifest = MonthManifest(part.pair, part.side, part.year, part.month)
    manifest.days = [
        DayStatus(part.pair, part.side, part.year, part.month, day, "failed")
        for day in range(1, 15)
    ]
    save_month_manifest(runner.raw_dir(tmp_path), manifest)
    runner.save_state(
        tmp_path,
        {
            "gate_id": runner.GATE_ID,
            "queue_order": "test",
            "total_partitions": 1,
            "partitions": {
                part.key: {
                    "pair": part.pair,
                    "year": part.year,
                    "month": part.month,
                    "side": part.side,
                    "state": "FAILED_RETRYABLE",
                    "attempts": 4,
                    "outer_failure_attempts": 1,
                }
            },
        },
    )
    outcomes = ["complete"] * 13 + ["failed"]

    def fake_download(*_args, **_kwargs) -> DayStatus:
        day = len(outcomes) - outcomes.count("complete") - outcomes.count("failed") + 1
        status = outcomes.pop(0)
        return DayStatus(
            part.pair,
            part.side,
            part.year,
            part.month,
            day,
            status,
            rows=1 if status == "complete" else 0,
            native_primary_status="PASS" if status == "complete" else "FAIL",
            effective_http_client="python_urllib" if status == "complete" else "curl.exe",
            native_content_length=10,
        )

    monkeypatch.setattr(runner, "download_native_day_with_checkpoint", fake_download)
    result = runner.acquire_one_native(tmp_path, part, max_day_requests=14)
    assert result["attempts"] == 5
    assert result["outer_failure_attempts"] == 1
    assert result["outer_failure_attempt_increment"] == 0
    assert result["failure_category"] == "SUCCESSFUL_PARTIAL_MONTH"
    assert result["state"] == "FAILED_RETRYABLE"


def test_five_successful_partial_cycles_do_not_terminalize(
    tmp_path: Path, monkeypatch
) -> None:
    part = _one_part()
    monkeypatch.setattr(runner, "partition_queue", lambda *args, **kwargs: [part])
    manifest = MonthManifest(part.pair, part.side, part.year, part.month)
    manifest.days = [DayStatus(part.pair, part.side, part.year, part.month, 1, "failed")]
    save_month_manifest(runner.raw_dir(tmp_path), manifest)
    runner.save_state(
        tmp_path,
        {
            "partitions": {
                part.key: {
                    "pair": part.pair,
                    "year": part.year,
                    "month": part.month,
                    "side": part.side,
                    "state": "FAILED_RETRYABLE",
                    "attempts": 5,
                    "partition_cycles": 5,
                    "outer_failure_attempts": 0,
                    "failure_category": "SUCCESSFUL_PARTIAL_MONTH",
                }
            }
        },
    )
    refreshed = runner.refresh_state_from_manifests(tmp_path)
    assert refreshed["partitions"][part.key]["state"] == "FAILED_RETRYABLE"
    assert refreshed["partitions"][part.key]["outer_failure_attempts"] == 0


def test_four_outer_failures_plus_successful_partial_cycle_remain_retryable(
    tmp_path: Path, monkeypatch
) -> None:
    part = _one_part()
    monkeypatch.setattr(runner, "partition_queue", lambda *args, **kwargs: [part])
    manifest = MonthManifest(part.pair, part.side, part.year, part.month)
    manifest.days = [DayStatus(part.pair, part.side, part.year, part.month, 1, "failed")]
    save_month_manifest(runner.raw_dir(tmp_path), manifest)
    runner.save_state(
        tmp_path,
        {
            "partitions": {
                part.key: {
                    "pair": part.pair,
                    "year": part.year,
                    "month": part.month,
                    "side": part.side,
                    "state": "FAILED_RETRYABLE",
                    "attempts": 5,
                    "outer_failure_attempts": 4,
                    "failure_category": "SUCCESSFUL_PARTIAL_MONTH",
                }
            }
        },
    )
    refreshed = runner.refresh_state_from_manifests(tmp_path)
    item = refreshed["partitions"][part.key]
    assert item["state"] == "FAILED_RETRYABLE"
    assert item["outer_failure_attempts"] == 4


def test_day_attempts_above_cap_do_not_terminalize_partition(
    tmp_path: Path, monkeypatch
) -> None:
    part = _one_part()
    monkeypatch.setattr(runner, "partition_queue", lambda *args, **kwargs: [part])
    manifest = MonthManifest(part.pair, part.side, part.year, part.month)
    manifest.days = [
        DayStatus(part.pair, part.side, part.year, part.month, 1, "failed", attempts=6)
    ]
    save_month_manifest(runner.raw_dir(tmp_path), manifest)
    runner.save_state(
        tmp_path,
        {
            "partitions": {
                part.key: {
                    "pair": part.pair,
                    "year": part.year,
                    "month": part.month,
                    "side": part.side,
                    "state": "FAILED_RETRYABLE",
                    "attempts": 0,
                    "outer_failure_attempts": 0,
                }
            }
        },
    )
    refreshed = runner.refresh_state_from_manifests(tmp_path)
    item = refreshed["partitions"][part.key]
    assert item["state"] == "FAILED_RETRYABLE"
    assert item["outer_failure_attempts"] == 0


def test_legacy_misterminalized_state_is_corrected_with_history_preserved(
    tmp_path: Path, monkeypatch
) -> None:
    part = _one_part()
    monkeypatch.setattr(runner, "partition_queue", lambda *args, **kwargs: [part])
    manifest = MonthManifest(part.pair, part.side, part.year, part.month)
    manifest.days = [DayStatus(part.pair, part.side, part.year, part.month, 1, "failed")]
    save_month_manifest(runner.raw_dir(tmp_path), manifest)
    for attempt in (1, 2):
        runner.append_event(
            tmp_path,
            {
                "partition": part.key,
                "state": "FAILED_RETRYABLE",
                "attempts": attempt,
                "failure_category": "UNKNOWN_RETRYABLE_FAILURE_BEFORE_ATTEMPT_CAP",
            },
        )
    runner.save_state(
        tmp_path,
        {
            "partitions": {
                part.key: {
                    "pair": part.pair,
                    "year": part.year,
                    "month": part.month,
                    "side": part.side,
                    "state": "FAILED_TERMINAL",
                    "attempts": 5,
                    "terminal_reason": "RETRY_ATTEMPTS_EXHAUSTED",
                }
            }
        },
    )
    refreshed = runner.refresh_state_from_manifests(tmp_path)
    item = refreshed["partitions"][part.key]
    assert item["state"] == "FAILED_RETRYABLE"
    assert item["legacy_partition_attempt_count"] == 5
    assert item["outer_failure_attempts"] == 2
    assert item["attempt_accounting_correction"]["correction_id"] == (
        runner.ATTEMPT_ACCOUNTING_CORRECTION_ID
    )
    events = runner.read_jsonl_records(runner.events_path(tmp_path))
    assert any(row.get("event_type") == runner.ATTEMPT_ACCOUNTING_CORRECTION_ID for row in events)


def test_empty_provider_error_produces_structured_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    part = _one_part()
    monkeypatch.setattr(runner, "partition_queue", lambda *args, **kwargs: [part])
    monkeypatch.setattr(runner, "results_dir", lambda: tmp_path / "results")
    manifest = MonthManifest(part.pair, part.side, part.year, part.month)
    manifest.days = [
        DayStatus(
            part.pair,
            part.side,
            part.year,
            part.month,
            1,
            "failed",
            failure_category="NO_PROVIDER_DATA",
            error="",
            attempts=1,
        )
    ]
    save_month_manifest(runner.raw_dir(tmp_path), manifest)
    state = {
        "gate_id": runner.GATE_ID,
        "queue_order": "test",
        "total_partitions": 1,
        "partitions": {
            part.key: {
                "pair": part.pair,
                "year": part.year,
                "month": part.month,
                "side": part.side,
                "state": "FAILED_RETRYABLE",
            }
        },
    }
    runner.save_state(tmp_path, state)
    payload = runner.analyze_retryable_failures_v2(tmp_path)
    row = payload["rows"][0]
    assert row["error_fingerprint"]
    assert row["evidence"]["structured_reason"] == "MONTH_INCOMPLETE_WITH_FAILED_DAYS"


def test_max_partitions_preserves_deterministic_queue_order(
    tmp_path: Path, monkeypatch
) -> None:
    parts = [
        runner.Partition("EURUSD", 2010, 1, "bid"),
        runner.Partition("EURUSD", 2010, 1, "ask"),
        runner.Partition("GBPUSD", 2010, 1, "bid"),
    ]
    scheduled: list[str] = []

    def fake_acquire(data_root: Path, part: runner.Partition) -> dict:
        scheduled.append(part.key)
        return {
            "partition": part.key,
            "pair": part.pair,
            "year": part.year,
            "month": part.month,
            "side": part.side,
            "state": "FAILED_RETRYABLE",
            "attempts": 1,
        }

    monkeypatch.setattr(runner, "recertify_clean_room", lambda *args, **kwargs: {})
    monkeypatch.setattr(runner, "partition_queue", lambda *args, **kwargs: parts)
    monkeypatch.setattr(runner, "acquire_one", fake_acquire)
    monkeypatch.setattr(
        runner,
        "acquisition_summary",
        lambda data_root: {"status": "PASS", "scheduled": scheduled},
    )
    args = argparse.Namespace(
        pair=None,
        year=None,
        month=None,
        side=None,
        retry_failed=False,
        resume=True,
        max_workers=2,
        max_partitions=2,
    )
    runner.run_acquisition(args, tmp_path)
    assert scheduled == [parts[0].key, parts[1].key]


def test_operational_cycle_invokes_acquire_certify_and_canonicalize(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[str] = []

    def fake_run_acquisition(args, data_root):
        calls.append("acquire")
        return {"status": "PASS"}

    def fake_run_certification(data_root):
        calls.append("certify")
        return {"status": "INCOMPLETE"}

    def fake_run_canonicalize(data_root):
        calls.append("canonicalize")
        return {
            "status": "INCOMPLETE",
            "reused_valid_partitions": 0,
            "newly_built_partitions": 0,
            "rebuilt_invalid_partitions": 0,
            "canonicalization_failures": 0,
        }

    monkeypatch.setattr(runner, "refresh_state_from_manifests", lambda data_root: {})
    monkeypatch.setattr(runner, "run_acquisition", fake_run_acquisition)
    monkeypatch.setattr(runner, "run_certification", fake_run_certification)
    monkeypatch.setattr(runner, "run_canonicalize", fake_run_canonicalize)
    monkeypatch.setattr(runner, "acquisition_summary", lambda data_root: {"status": "PASS"})
    args = argparse.Namespace(retry_failed=False, max_partitions=48)
    runner.run_operational_cycle(args, tmp_path)
    assert calls == ["acquire", "certify", "canonicalize"]


def test_incremental_canonicalization_skips_valid_output(
    tmp_path: Path, monkeypatch
) -> None:
    data_root = tmp_path / "data"
    results = tmp_path / "results"
    pair = "EURUSD"
    year = 2010
    month = 1
    for root, timeframe in (
        (runner.m1_dir(data_root), "M1"),
        (runner.m5_dir(data_root), "M5"),
        (runner.feature_dir(data_root), "M1"),
    ):
        path = runner.canonical_partition_path(root, pair, timeframe, year, month)
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"timestamp": [pd.Timestamp("2010-01-01", tz="UTC")]}).to_parquet(
            path, index=False
        )
    m1_hash = runner.file_sha256(
        runner.canonical_partition_path(runner.m1_dir(data_root), pair, "M1", year, month)
    )
    m5_hash = runner.file_sha256(
        runner.canonical_partition_path(runner.m5_dir(data_root), pair, "M5", year, month)
    )
    feature_hash = runner.file_sha256(
        runner.canonical_partition_path(
            runner.feature_dir(data_root), pair, "M1", year, month
        )
    )
    runner.write_json(
        results / "m1_alignment_certification.json",
        {"rows": [{"pair": pair, "year": year, "month": month, "sha256": m1_hash}]},
    )
    runner.write_json(
        results / "m5_partition_manifest.json",
        {"partitions": [{"pair": pair, "year": year, "month": month, "sha256": m5_hash}]},
    )
    runner.write_json(
        results / "feature_partition_manifest.json",
        {
            "partitions": [
                {"pair": pair, "year": year, "month": month, "sha256": feature_hash}
            ]
        },
    )
    state = {
        "partitions": {
            f"{year:04d}-{month:02d}:{pair}:bid": {"state": "CERTIFIED"},
            f"{year:04d}-{month:02d}:{pair}:ask": {"state": "CERTIFIED"},
        }
    }
    monkeypatch.setattr(runner, "results_dir", lambda: results)
    monkeypatch.setattr(runner, "recertify_clean_room", lambda *args, **kwargs: {})
    monkeypatch.setattr(runner, "refresh_state_from_manifests", lambda data_root: state)
    monkeypatch.setattr(runner, "INSTRUMENTS", (pair,))
    monkeypatch.setattr(runner, "YEARS", range(year, year + 1))
    monkeypatch.setattr(runner, "MONTHS", range(month, month + 1))
    result = runner.run_canonicalize(data_root)
    assert result["reused_valid_partitions"] == 1
    assert result["newly_built_partitions"] == 0


def test_discovery_refuses_missing_dataset_freeze() -> None:
    assert runner.MATERIALIZATION_ID_V2 == "A0R2_EXACT_TRIAL_CONFIGURATION_MATERIALIZATION_V2"
    assert runner.MATERIALIZATION_V2_SHA256
