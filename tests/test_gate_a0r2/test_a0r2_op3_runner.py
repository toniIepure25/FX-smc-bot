"""A0R2-OP3 lease, diagnostics and long-run controls."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from fx_smc_bot.data.daily_checkpoint import DayStatus, MonthManifest, save_month_manifest
from fx_smc_bot.data.dukascopy_node_provider import ProviderCallResult
from scripts import run_gate_a0r2 as runner


def _part(side: str = "bid") -> runner.Partition:
    return runner.Partition("EURUSD", 2010, 1, side)


def _state_with_running(tmp_path: Path, part: runner.Partition) -> None:
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
                    "state": "RUNNING",
                    "attempts": 2,
                }
            },
        },
    )


def _native_retry_args(**overrides) -> argparse.Namespace:
    values = {
        "recover_orphaned_running": False,
        "transport": "native",
        "pair": None,
        "year": None,
        "month": None,
        "side": None,
        "retry_failed": True,
        "resume": True,
        "repair_missing_days": True,
        "max_workers": 1,
        "native_workers": 1,
        "max_partitions": 1,
        "max_day_requests": 10,
        "max_runtime_seconds": 0,
        "max_runtime_minutes": 0,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _write_ready_handoff_state(
    tmp_path: Path,
    *,
    updated_at: datetime | None = None,
    latest_run_id: str = "native-pass",
    consumed: bool = False,
) -> None:
    payload = {
        "artifact_id": "A0R2_NATIVE_HEALTH_WATCH_STATE_V1",
        "gate_id": runner.GATE_ID,
        "status": "NATIVE_HEALTH_READY",
        "attempts_completed": 2,
        "consecutive_passing_runs": 2,
        "required_consecutive_health_passes": 2,
        "partition_attempts_consumed": 0,
        "updated_at": (updated_at or datetime.now(timezone.utc)).isoformat(),
        "history": [
            {
                "attempt": 2,
                "status": "PASS",
                "latest_status": "PASS",
                "latest_run_id": latest_run_id,
            }
        ],
    }
    if consumed:
        payload["handoff_consumed_health_run_id"] = latest_run_id
        payload["handoff_consumed_at"] = datetime.now(timezone.utc).isoformat()
        payload["handoff_consumed_by_runner_id"] = "already-used"
    runner.write_json(runner.native_health_watch_state_path(tmp_path), payload)


def _save_missing_manifest(part: runner.Partition, tmp_path: Path, missing_days: int = 1) -> None:
    manifest = MonthManifest(part.pair, part.side, part.year, part.month)
    manifest.days = [
        DayStatus(
            part.pair,
            part.side,
            part.year,
            part.month,
            day,
            "failed" if day <= missing_days else "complete",
            rows=0 if day <= missing_days else 1,
        )
        for day in range(1, 32)
    ]
    save_month_manifest(runner.raw_dir(tmp_path), manifest)


def _prepare_native_retry(
    monkeypatch,
    tmp_path: Path,
    parts: list[runner.Partition],
    *,
    summary_status: str = "PASS",
    preflight_status: str = "PASS",
) -> list[runner.Partition]:
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
                    "attempts": 1,
                }
                for part in parts
            }
        },
    )
    for part in parts:
        _save_missing_manifest(part, tmp_path)
    monkeypatch.setattr(runner, "recertify_clean_room", lambda *args, **kwargs: {})
    monkeypatch.setattr(runner, "partition_queue", lambda *args, **kwargs: parts)
    monkeypatch.setattr(runner, "select_transport", lambda _transport: ("native", "test", {}))
    monkeypatch.setattr(
        runner,
        "refresh_state_from_manifests",
        lambda data_root, **_kwargs: runner.load_state(data_root),
    )
    monkeypatch.setattr(runner, "results_dir", lambda: tmp_path / "results")
    monkeypatch.setattr(
        runner,
        "write_provider_health_summary",
        lambda _root: {
            "status": summary_status,
            "latest_status": summary_status,
            "latest_run_id": "native-pass",
        },
    )
    preflights: list[runner.Partition] = []

    def fake_preflight(_root: Path) -> dict:
        preflights.append(parts[0])
        return {"status": preflight_status}

    monkeypatch.setattr(runner, "run_native_health_controls", fake_preflight)
    return preflights


def test_orphaned_running_with_complete_manifest(tmp_path: Path, monkeypatch) -> None:
    part = _part()
    _state_with_running(tmp_path, part)
    manifest = MonthManifest(part.pair, part.side, part.year, part.month)
    manifest.compacted = True
    manifest.compacted_rows = 1
    manifest.compacted_checksum = "abc"
    manifest.days = [
        DayStatus(part.pair, part.side, part.year, part.month, day, "market_closed")
        for day in range(1, 32)
    ]
    manifest.days[0].status = "complete"
    save_month_manifest(runner.raw_dir(tmp_path), manifest)
    monkeypatch.setattr(runner, "partition_queue", lambda *args, **kwargs: [part])
    monkeypatch.setattr(runner, "results_dir", lambda: tmp_path / "results")
    payload = runner.recover_orphaned_running(tmp_path, explicit=True)
    state = runner.load_state(tmp_path)
    assert payload["recovered_count"] == 1
    assert state["partitions"][part.key]["state"] == "COMPLETE_PENDING_CERTIFICATION"


def test_orphaned_running_with_partial_manifest(tmp_path: Path, monkeypatch) -> None:
    part = _part()
    _state_with_running(tmp_path, part)
    manifest = MonthManifest(part.pair, part.side, part.year, part.month)
    manifest.days = [DayStatus(part.pair, part.side, part.year, part.month, 1, "failed")]
    save_month_manifest(runner.raw_dir(tmp_path), manifest)
    monkeypatch.setattr(runner, "partition_queue", lambda *args, **kwargs: [part])
    monkeypatch.setattr(runner, "results_dir", lambda: tmp_path / "results")
    runner.recover_orphaned_running(tmp_path, explicit=True)
    item = runner.load_state(tmp_path)["partitions"][part.key]
    assert item["state"] == "FAILED_RETRYABLE"
    assert item["attempts"] == 2
    assert item["failure_category"] == "PROCESS_INTERRUPTED_WITH_PARTIAL_CHECKPOINT"


def test_orphaned_running_without_manifest(tmp_path: Path, monkeypatch) -> None:
    part = _part()
    _state_with_running(tmp_path, part)
    monkeypatch.setattr(runner, "partition_queue", lambda *args, **kwargs: [part])
    monkeypatch.setattr(runner, "results_dir", lambda: tmp_path / "results")
    runner.recover_orphaned_running(tmp_path, explicit=True)
    item = runner.load_state(tmp_path)["partitions"][part.key]
    assert item["state"] == "FAILED_RETRYABLE"
    assert item["failure_category"] == "PROCESS_INTERRUPTED_BEFORE_CHECKPOINT"


def test_live_process_lease_prevents_competing_runner(tmp_path: Path, monkeypatch) -> None:
    runner.write_lease(
        tmp_path,
        run_id="abc",
        stage="acquire",
        worker_count=1,
        current_partitions=[],
    )
    monkeypatch.setattr(runner, "recertify_clean_room", lambda *args, **kwargs: {})
    args = argparse.Namespace(
        recover_orphaned_running=False,
        pair=None,
        year=None,
        month=None,
        side=None,
        retry_failed=False,
        resume=True,
        max_workers=1,
        max_partitions=1,
    )
    try:
        runner.run_acquisition(args, tmp_path)
    except ValueError as exc:
        assert "ACTIVE_LEASE" in str(exc)
    else:
        raise AssertionError("lease did not block competing runner")


def test_heartbeat_update(tmp_path: Path) -> None:
    runner.write_lease(
        tmp_path,
        run_id="abc",
        stage="acquire",
        worker_count=1,
        current_partitions=[],
    )
    runner.update_lease_heartbeat(tmp_path, ["2010-01:EURUSD:bid"])
    lease = runner.read_lease(tmp_path)
    assert lease is not None
    assert lease["current_partition_ids"] == ["2010-01:EURUSD:bid"]


def test_provider_diagnostics_preserve_code_and_fingerprints() -> None:
    result = ProviderCallResult(
        rows=[],
        succeeded=False,
        error_message="fetch failed",
        error_code="ECONNRESET",
        stack_fingerprint="stack123",
        stderr_excerpt="stderr",
        stderr_fingerprint="stderr123",
        stdout_record_types=["acquisition_error"],
        return_code=1,
        timed_out=False,
        duration_ms=10,
        output_file_reported=False,
        output_file_found=False,
    )
    payload = runner.provider_diagnostic_payload(_part(), result, request_kind="test")
    assert payload["error_code"] == "ECONNRESET"
    assert payload["stack_fingerprint"] == "stack123"
    assert payload["stderr_fingerprint"] == "stderr123"
    assert payload["failure_category"] == "PROVIDER_CONNECTION_RESET"


def test_generic_node_error_receives_structured_category() -> None:
    result = ProviderCallResult(
        rows=[],
        succeeded=False,
        error_message="Unknown error",
        error_code="",
        stack_fingerprint="stack123",
        stderr_excerpt="",
        stderr_fingerprint="",
        stdout_record_types=["acquisition_error"],
        return_code=1,
        timed_out=False,
        duration_ms=10,
        output_file_reported=False,
        output_file_found=False,
    )
    assert runner.classify_provider_diagnostic(result) == "PROVIDER_LIBRARY_ERROR"


def test_circuit_breaker_trigger(monkeypatch, tmp_path: Path) -> None:
    parts = [runner.Partition("EURUSD", 2010, i + 1, "bid") for i in range(8)]

    def fake_acquire(data_root: Path, part: runner.Partition) -> dict:
        return {
            "partition": part.key,
            "pair": part.pair,
            "year": part.year,
            "month": part.month,
            "side": part.side,
            "state": "FAILED_RETRYABLE",
            "attempts": 1,
            "error": "provider library error",
        }

    monkeypatch.setattr(runner, "recertify_clean_room", lambda *args, **kwargs: {})
    monkeypatch.setattr(runner, "partition_queue", lambda *args, **kwargs: parts)
    monkeypatch.setattr(runner, "acquire_one", fake_acquire)
    args = argparse.Namespace(
        recover_orphaned_running=False,
        pair=None,
        year=None,
        month=None,
        side=None,
        retry_failed=False,
        resume=True,
        max_workers=1,
        max_partitions=8,
    )
    progress = runner.run_acquisition(args, tmp_path)
    assert progress["status"] == "PROVIDER_COOLDOWN_REQUIRED"
    assert progress["circuit_breaker_activations"] == 1


def test_fresh_native_health_handoff_skips_duplicate_preflight(
    monkeypatch, tmp_path: Path
) -> None:
    part = runner.Partition("EURUSD", 2010, 1, "bid")
    preflights = _prepare_native_retry(monkeypatch, tmp_path, [part])
    _write_ready_handoff_state(tmp_path)
    executed: list[str] = []

    def fake_acquire_native(
        _data_root: Path, queued: runner.Partition, max_day_requests: int | None = None
    ) -> dict:
        executed.append(queued.key)
        return {
            "partition": queued.key,
            "pair": queued.pair,
            "year": queued.year,
            "month": queued.month,
            "side": queued.side,
            "state": "COMPLETE_PENDING_CERTIFICATION",
            "attempts": 2,
            "native_daily_requests": 1,
            "native_daily_successes": 1,
            "native_daily_failures": 0,
        }

    monkeypatch.setattr(runner, "acquire_one_native", fake_acquire_native)

    progress = runner.run_acquisition(_native_retry_args(), tmp_path)
    state = runner.read_json(runner.native_health_watch_state_path(tmp_path))

    assert preflights == []
    assert executed == [part.key]
    assert progress["health_gate_source"] == "FRESH_NATIVE_HEALTH_WATCH_HANDOFF"
    assert progress["health_gate_reused"] is True
    assert progress["fresh_health_handoffs_consumed"] == 1
    assert state["handoff_consumed_health_run_id"] == "native-pass"


def test_stale_native_health_handoff_runs_normal_preflight(
    monkeypatch, tmp_path: Path
) -> None:
    part = runner.Partition("EURUSD", 2010, 1, "bid")
    preflights = _prepare_native_retry(monkeypatch, tmp_path, [part])
    _write_ready_handoff_state(
        tmp_path,
        updated_at=datetime.now(timezone.utc) - timedelta(seconds=61),
    )
    executed: list[str] = []

    def fake_acquire_native(
        _data_root: Path, queued: runner.Partition, max_day_requests: int | None = None
    ) -> dict:
        executed.append(queued.key)
        return {
            "partition": queued.key,
            "pair": queued.pair,
            "year": queued.year,
            "month": queued.month,
            "side": queued.side,
            "state": "COMPLETE_PENDING_CERTIFICATION",
            "attempts": 2,
            "native_daily_requests": 1,
            "native_daily_successes": 1,
            "native_daily_failures": 0,
        }

    monkeypatch.setattr(runner, "acquire_one_native", fake_acquire_native)

    runner.run_acquisition(_native_retry_args(), tmp_path)

    assert len(preflights) == 1
    assert executed == [part.key]


def test_fresh_native_handoff_with_fail_summary_runs_normal_preflight(
    monkeypatch, tmp_path: Path
) -> None:
    part = runner.Partition("EURUSD", 2010, 1, "bid")
    preflights = _prepare_native_retry(monkeypatch, tmp_path, [part], summary_status="FAIL")
    _write_ready_handoff_state(tmp_path)
    executed: list[str] = []

    def fake_acquire_native(
        _data_root: Path, queued: runner.Partition, max_day_requests: int | None = None
    ) -> dict:
        executed.append(queued.key)
        return {
            "partition": queued.key,
            "pair": queued.pair,
            "year": queued.year,
            "month": queued.month,
            "side": queued.side,
            "state": "COMPLETE_PENDING_CERTIFICATION",
            "attempts": 2,
            "native_daily_requests": 1,
            "native_daily_successes": 1,
            "native_daily_failures": 0,
        }

    monkeypatch.setattr(runner, "acquire_one_native", fake_acquire_native)

    runner.run_acquisition(_native_retry_args(), tmp_path)

    assert len(preflights) == 1
    assert executed == [part.key]


def test_consumed_native_health_handoff_cannot_be_reused(
    monkeypatch, tmp_path: Path
) -> None:
    part = runner.Partition("EURUSD", 2010, 1, "bid")
    preflights = _prepare_native_retry(monkeypatch, tmp_path, [part])
    _write_ready_handoff_state(tmp_path, consumed=True)
    executed: list[str] = []
    monkeypatch.setattr(
        runner,
        "acquire_one_native",
        lambda _root, queued, max_day_requests=None: executed.append(queued.key)
        or {
            "partition": queued.key,
            "pair": queued.pair,
            "year": queued.year,
            "month": queued.month,
            "side": queued.side,
            "state": "COMPLETE_PENDING_CERTIFICATION",
            "attempts": 2,
            "native_daily_requests": 1,
            "native_daily_successes": 1,
            "native_daily_failures": 0,
        },
    )

    runner.run_acquisition(_native_retry_args(), tmp_path)

    assert len(preflights) == 1
    assert executed == [part.key]


def test_fresh_native_handoff_first_two_failures_stop_without_third(
    monkeypatch, tmp_path: Path
) -> None:
    parts = [runner.Partition("EURUSD", 2010, month, "bid") for month in range(1, 4)]
    preflights = _prepare_native_retry(monkeypatch, tmp_path, parts)
    _write_ready_handoff_state(tmp_path)
    executed: list[str] = []

    def fake_acquire_native(
        _data_root: Path, queued: runner.Partition, max_day_requests: int | None = None
    ) -> dict:
        executed.append(queued.key)
        return {
            "partition": queued.key,
            "pair": queued.pair,
            "year": queued.year,
            "month": queued.month,
            "side": queued.side,
            "state": "FAILED_RETRYABLE",
            "attempts": 2,
            "error": "HTTP 503",
            "failure_category": "NATIVE_BI5_TRANSPORT_FAILURE",
            "native_daily_requests": 1,
            "native_daily_successes": 0,
            "native_daily_failures": 1,
            "native_curl_fallback_successes": 0,
        }

    monkeypatch.setattr(runner, "acquire_one_native", fake_acquire_native)

    progress = runner.run_acquisition(
        _native_retry_args(max_partitions=3, native_workers=2, max_day_requests=3), tmp_path
    )

    assert preflights == []
    assert executed == [parts[0].key, parts[1].key]
    assert runner.load_state(tmp_path)["partitions"][parts[2].key]["attempts"] == 1
    assert progress["status"] == "PROVIDER_COOLDOWN_REQUIRED"
    assert progress["fresh_handoff_initial_circuit_breaker"] is True
    assert progress["circuit_breaker_activations"] == 1


def test_operational_cycle_reports_acquisition_health_handoff(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(runner, "refresh_state_from_manifests", lambda _root: {})
    monkeypatch.setattr(
        runner,
        "run_acquisition",
        lambda _args, _root: {
            "status": "A0R2_OPERATIONAL_CHECKPOINT_NATIVE_ACQUISITION_IN_PROGRESS",
            "health_gate_source": "FRESH_NATIVE_HEALTH_WATCH_HANDOFF",
            "health_gate_reused": True,
            "health_gate_age_seconds": 12.5,
            "fresh_health_handoffs_consumed": 1,
            "direct_repair_health_gates": 0,
            "native_day_request_budget_used": 3,
        },
    )
    monkeypatch.setattr(runner, "run_certification", lambda _root: {"status": "INCOMPLETE"})
    monkeypatch.setattr(
        runner,
        "run_canonicalize",
        lambda _root: {
            "status": "INCOMPLETE",
            "reused_valid_partitions": 0,
            "newly_built_partitions": 0,
            "rebuilt_invalid_partitions": 0,
            "canonicalization_failures": 0,
        },
    )
    monkeypatch.setattr(
        runner,
        "acquisition_summary",
        lambda _root: {
            "status": "A0R2_OPERATIONAL_CHECKPOINT_ACQUISITION_IN_PROGRESS",
            "certified_partitions": 0,
            "retryable_failures": 0,
            "planned_partitions": 0,
            "terminal_failures": 0,
            "running_partitions": 0,
        },
    )

    progress = runner.run_operational_cycle(
        _native_retry_args(max_operational_cycles=1), tmp_path
    )

    assert progress["health_gate_source"] == "FRESH_NATIVE_HEALTH_WATCH_HANDOFF"
    assert progress["health_gate_reused"] is True
    assert progress["fresh_health_handoffs_consumed"] == 1
    assert progress["direct_repair_health_gates"] == 0
    assert progress["operational_cycle"]["health_gate_source"] == (
        "FRESH_NATIVE_HEALTH_WATCH_HANDOFF"
    )
    assert progress["operational_cycle"]["native_day_request_budget_used"] == 3


def test_retryable_repair_prioritizes_closure_missing_days(
    monkeypatch, tmp_path: Path
) -> None:
    large = runner.Partition("EURUSD", 2010, 1, "bid")
    almost_done = runner.Partition("GBPUSD", 2010, 1, "bid")
    middle = runner.Partition("USDJPY", 2010, 1, "bid")
    parts = [large, middle, almost_done]

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
                    "attempts": 1,
                }
                for part in parts
            }
        },
    )

    def save_manifest(part: runner.Partition, missing_days: int) -> None:
        manifest = MonthManifest(part.pair, part.side, part.year, part.month)
        manifest.days = [
            DayStatus(
                part.pair,
                part.side,
                part.year,
                part.month,
                day,
                "failed" if day <= missing_days else "complete",
                rows=0 if day <= missing_days else 1,
            )
            for day in range(1, 32)
        ]
        save_month_manifest(runner.raw_dir(tmp_path), manifest)

    save_manifest(large, 20)
    save_manifest(middle, 5)
    save_manifest(almost_done, 2)

    executed: list[str] = []

    def fake_acquire_native(
        _data_root: Path, part: runner.Partition, max_day_requests: int | None = None
    ) -> dict:
        executed.append(part.key)
        return {
            "partition": part.key,
            "pair": part.pair,
            "year": part.year,
            "month": part.month,
            "side": part.side,
            "state": "FAILED_RETRYABLE",
            "attempts": 2,
            "native_daily_requests": 0,
        }

    monkeypatch.setattr(runner, "recertify_clean_room", lambda *args, **kwargs: {})
    monkeypatch.setattr(runner, "partition_queue", lambda *args, **kwargs: parts)
    monkeypatch.setattr(runner, "select_transport", lambda _transport: ("native", "test", {}))
    monkeypatch.setattr(runner, "run_native_health_controls", lambda _root: {"status": "PASS"})
    monkeypatch.setattr(
        runner,
        "refresh_state_from_manifests",
        lambda data_root, **_kwargs: runner.load_state(data_root),
    )
    monkeypatch.setattr(runner, "acquire_one_native", fake_acquire_native)

    args = argparse.Namespace(
        recover_orphaned_running=False,
        transport="native",
        pair=None,
        year=None,
        month=None,
        side=None,
        retry_failed=True,
        resume=True,
        repair_missing_days=True,
        max_workers=1,
        native_workers=1,
        max_partitions=2,
        max_day_requests=10,
        max_runtime_seconds=0,
        max_runtime_minutes=0,
    )

    runner.run_acquisition(args, tmp_path)

    assert executed == [almost_done.key, middle.key]


def test_retryable_repair_prefers_eligible_over_cooling_partition(
    monkeypatch, tmp_path: Path
) -> None:
    cooling = runner.Partition("GBPUSD", 2010, 1, "bid")
    eligible = runner.Partition("USDJPY", 2010, 1, "bid")
    parts = [cooling, eligible]
    future_retry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    runner.save_state(
        tmp_path,
        {
            "partitions": {
                cooling.key: {
                    "pair": cooling.pair,
                    "year": cooling.year,
                    "month": cooling.month,
                    "side": cooling.side,
                    "state": "FAILED_RETRYABLE",
                    "attempts": 1,
                    "next_eligible_retry_timestamp": future_retry,
                },
                eligible.key: {
                    "pair": eligible.pair,
                    "year": eligible.year,
                    "month": eligible.month,
                    "side": eligible.side,
                    "state": "FAILED_RETRYABLE",
                    "attempts": 1,
                },
            }
        },
    )

    def save_manifest(part: runner.Partition, missing_days: int) -> None:
        manifest = MonthManifest(part.pair, part.side, part.year, part.month)
        manifest.days = [
            DayStatus(
                part.pair,
                part.side,
                part.year,
                part.month,
                day,
                "failed" if day <= missing_days else "complete",
                rows=0 if day <= missing_days else 1,
            )
            for day in range(1, 32)
        ]
        save_month_manifest(runner.raw_dir(tmp_path), manifest)

    save_manifest(cooling, 1)
    save_manifest(eligible, 2)
    executed: list[str] = []

    def fake_acquire_native(
        _data_root: Path, part: runner.Partition, max_day_requests: int | None = None
    ) -> dict:
        executed.append(part.key)
        return {
            "partition": part.key,
            "pair": part.pair,
            "year": part.year,
            "month": part.month,
            "side": part.side,
            "state": "FAILED_RETRYABLE",
            "attempts": 2,
            "native_daily_requests": 0,
        }

    monkeypatch.setattr(runner, "recertify_clean_room", lambda *args, **kwargs: {})
    monkeypatch.setattr(runner, "partition_queue", lambda *args, **kwargs: parts)
    monkeypatch.setattr(runner, "select_transport", lambda _transport: ("native", "test", {}))
    monkeypatch.setattr(runner, "run_native_health_controls", lambda _root: {"status": "PASS"})
    monkeypatch.setattr(
        runner,
        "refresh_state_from_manifests",
        lambda data_root, **_kwargs: runner.load_state(data_root),
    )
    monkeypatch.setattr(runner, "acquire_one_native", fake_acquire_native)

    args = argparse.Namespace(
        recover_orphaned_running=False,
        transport="native",
        pair=None,
        year=None,
        month=None,
        side=None,
        retry_failed=True,
        resume=True,
        repair_missing_days=True,
        max_workers=1,
        native_workers=1,
        max_partitions=1,
        max_day_requests=10,
        max_runtime_seconds=0,
        max_runtime_minutes=0,
    )

    runner.run_acquisition(args, tmp_path)

    assert executed == [eligible.key]


def test_canonicalization_failure_identity_report(tmp_path: Path, monkeypatch) -> None:
    pair = "EURUSD"
    year = 2010
    month = 1
    bid = runner.Partition(pair, year, month, "bid")
    ask = runner.Partition(pair, year, month, "ask")
    runner.save_state(
        tmp_path,
        {
            "partitions": {
                bid.key: {"state": "CERTIFIED", "checksum": "bid"},
                ask.key: {"state": "CERTIFIED", "checksum": "ask"},
            }
        },
    )
    monkeypatch.setattr(runner, "recertify_clean_room", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        runner,
        "refresh_state_from_manifests",
        lambda data_root: runner.load_state(data_root),
    )
    monkeypatch.setattr(runner, "INSTRUMENTS", (pair,))
    monkeypatch.setattr(runner, "YEARS", range(year, year + 1))
    monkeypatch.setattr(runner, "MONTHS", range(month, month + 1))
    monkeypatch.setattr(runner, "results_dir", lambda: tmp_path / "results")
    monkeypatch.setattr(
        runner,
        "align_bid_ask_month",
        lambda *args, **kwargs: {"error": "bid file missing"},
    )
    result = runner.run_canonicalize(tmp_path)
    failure = runner.read_json(
        tmp_path / "results" / "canonicalization_failure_analysis.json"
    )
    assert result["canonicalization_failures"] == 1
    assert failure["rows"][0]["alignment_exception_category"] == "ALIGNMENT_EMPTY"


def test_valid_canonical_sidecar_reuse(tmp_path: Path) -> None:
    path = tmp_path / "part.parquet"
    pd.DataFrame({"timestamp": [pd.Timestamp("2010-01-01", tz="UTC")]}).to_parquet(
        path, index=False
    )
    output_sha = runner.file_sha256(path)
    runner.write_canonical_sidecar(
        path,
        pair="EURUSD",
        year=2010,
        month=1,
        bid_checksum="bid",
        ask_checksum="ask",
        output_sha=output_sha,
        row_count=1,
        layer="M1",
    )
    assert runner.valid_existing_parquet(path, output_sha)
    assert runner.read_json(runner.canonical_sidecar_path(path))["output_sha256"] == output_sha


def test_all_executable_v2_trials_have_supported_engine_routes(
    monkeypatch, tmp_path: Path
) -> None:
    results = tmp_path / "results"
    results.mkdir()
    source = runner.read_json(Path("results/gate_a0r2/trial_data_capability_v2_matrix.json"))
    runner.write_json(results / "trial_data_capability_v2_matrix.json", source)
    monkeypatch.setattr(runner, "results_dir", lambda: results)
    payload = runner.audit_discovery_engine_configuration_coverage()
    assert payload["status"] == "PASS"
    assert payload["unsupported_executable_configuration_count"] == 0
    assert payload["executable_trials"] == 1114
    assert payload["capability_invalid_trials"] == 86
