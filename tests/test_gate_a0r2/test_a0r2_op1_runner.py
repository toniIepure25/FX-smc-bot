"""A0R2-OP1 runner hardening tests."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from fx_smc_bot.data.daily_checkpoint import DayStatus, MonthManifest
from scripts import run_gate_a0r2 as runner


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_v2_trial_ids_match_v1_and_allocation_unchanged() -> None:
    v1 = _load_jsonl(Path("results/gate_a0r2/trial_materialization.jsonl"))
    v2 = _load_jsonl(Path("results/gate_a0r2/trial_materialization_v2.jsonl"))
    assert [row["trial_id"] for row in v2] == [row["trial_id"] for row in v1]
    assert sum(row["candidate_equivalent_weight"] for row in v2) == 1200
    assert runner.uncovered_categories(v2) == []


def test_v2_uses_only_frozen_categories() -> None:
    v2 = _load_jsonl(Path("results/gate_a0r2/trial_materialization_v2.jsonl"))
    for row in v2:
        family = row["family_id"]
        categories = row["full_configuration"]["frozen_categories"]
        assert set(categories) <= set(runner.FROZEN_CATEGORIES[family])
        for axis, value in categories.items():
            if isinstance(value, list):
                value = tuple(value)
            assert value in runner.FROZEN_CATEGORIES[family][axis]


def test_retry_failed_state_semantics() -> None:
    for state in ("CERTIFIED", "COMPLETE_PENDING_CERTIFICATION", "FAILED_TERMINAL"):
        assert not runner.should_acquire_partition(state, retry_failed=True, resume=True)
    assert not runner.should_acquire_partition(
        "FAILED_RETRYABLE", retry_failed=False, resume=True
    )
    assert runner.should_acquire_partition("FAILED_RETRYABLE", retry_failed=True, resume=True)
    assert runner.should_acquire_partition("PLANNED", retry_failed=False, resume=True)
    assert not runner.should_acquire_partition("PLANNED", retry_failed=True, resume=True)
    assert runner.should_acquire_partition(
        "RUNNING", retry_failed=False, resume=True, running_is_stale=True
    )
    assert not runner.should_acquire_partition(
        "RUNNING", retry_failed=False, resume=True, running_is_stale=False
    )


def test_failure_classification_and_attempt_cap() -> None:
    state, category = runner.classify_provider_failure("timeout", 1)
    assert state == "FAILED_RETRYABLE"
    assert category == "TRANSIENT_PROVIDER_OR_TRANSPORT_FAILURE"
    state, category = runner.classify_provider_failure("bad instrument", 1)
    assert state == "FAILED_TERMINAL"
    assert category == "NON_RETRYABLE_PROVIDER_OR_PROTOCOL_FAILURE"
    state, category = runner.classify_provider_failure("timeout", runner.MAX_PARTITION_ATTEMPTS)
    assert state == "FAILED_TERMINAL"
    assert category == "RETRY_ATTEMPTS_EXHAUSTED"


def test_thread_safe_jsonl_append(tmp_path: Path) -> None:
    def write_line(i: int) -> None:
        runner.append_event(tmp_path, {"i": i})

    threads = [threading.Thread(target=write_line, args=(i,)) for i in range(50)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    lines = (tmp_path / "checkpoints" / "a0r2_partition_events.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(lines) == 50
    assert sorted(json.loads(line)["i"] for line in lines) == list(range(50))


def _write_month(data_root: Path, part: runner.Partition, rows: list[dict]) -> str:
    path = runner.compacted_month_path(data_root, part)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows), encoding="utf-8")
    return runner.file_sha256(path)[:16]


def test_real_compacted_row_certification_passes(tmp_path: Path) -> None:
    part = runner.Partition("EURUSD", 2010, 1, "bid")
    rows = [
        {"timestamp": 1262304000000, "open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1},
        {"timestamp": 1262304060000, "open": 1.1, "high": 1.3, "low": 1.0, "close": 1.2},
    ]
    checksum = _write_month(tmp_path, part, rows)
    manifest = MonthManifest(part.pair, part.side, part.year, part.month)
    manifest.compacted = True
    manifest.compacted_rows = len(rows)
    manifest.compacted_checksum = checksum
    manifest.days = [
        DayStatus(part.pair, part.side, part.year, part.month, day, "market_closed")
        for day in range(1, 32)
    ]
    result = runner.certify_compacted_rows(tmp_path, manifest, part)
    assert all(result["checks"].values())


def test_checksum_mismatch_rejected(tmp_path: Path) -> None:
    part = runner.Partition("EURUSD", 2010, 1, "bid")
    _write_month(
        tmp_path,
        part,
        [{"timestamp": 1262304000000, "open": 1, "high": 1, "low": 1, "close": 1}],
    )
    manifest = MonthManifest(part.pair, part.side, part.year, part.month)
    manifest.compacted_checksum = "bad"
    result = runner.certify_compacted_rows(tmp_path, manifest, part)
    assert not result["checks"]["manifest_checksum_equality"]


def test_unauthorized_timestamp_rejected(tmp_path: Path) -> None:
    part = runner.Partition("EURUSD", 2010, 1, "bid")
    checksum = _write_month(
        tmp_path,
        part,
        [{"timestamp": 1264982400000, "open": 1, "high": 1, "low": 1, "close": 1}],
    )
    manifest = MonthManifest(part.pair, part.side, part.year, part.month)
    manifest.compacted_checksum = checksum
    result = runner.certify_compacted_rows(tmp_path, manifest, part)
    assert not result["checks"]["timestamps_inside_requested_month"]
    assert not result["checks"]["zero_unauthorized_timestamps"]


def test_bounded_in_flight_configuration() -> None:
    assert runner.MAX_PROVIDER_WORKERS == 2
    assert runner.MAX_IN_FLIGHT_FUTURES == 4
