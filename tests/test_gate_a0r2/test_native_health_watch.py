from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = ROOT / "scripts" / "run_gate_a0r2.py"
SPEC = importlib.util.spec_from_file_location("a0r2_native_health_runner", RUNNER_PATH)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


def _record(run_id: str, control: str, result: str) -> dict[str, object]:
    return {
        "record_type": "HEALTH_CONTROL",
        "transport": "NATIVE_BI5_TRANSPORT",
        "health_run_id": run_id,
        "control_id": control,
        "result": result,
        "timestamp": f"2026-01-01T00:00:0{control == 'B'}+00:00",
    }


def _summary(run_id: str, status: str) -> dict[str, object]:
    return {
        "record_type": "HEALTH_RUN_SUMMARY",
        "transport": "NATIVE_BI5_TRANSPORT",
        "health_run_id": run_id,
        "status": status,
        "timestamp": "2026-01-01T00:00:02+00:00",
        "completed_at": "2026-01-01T00:00:02+00:00",
    }


def _write_history(root: Path, records: list[dict[str, object]]) -> None:
    path = runner.native_health_history_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")


def test_health_summary_uses_only_complete_matching_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "results_dir", lambda: tmp_path / "results")
    records = [
        _record("one", "A", "PASS"),
        _record("one", "B", "PASS"),
        _summary("one", "PASS"),
        _record("two", "A", "FAIL"),
        _record("two", "B", "PASS"),
        _summary("two", "FAIL"),
        _record("interrupted", "A", "PASS"),
        _summary("interrupted", "PASS"),
        {"transport": "NATIVE_BI5_TRANSPORT", "result": "FAIL"},
    ]
    _write_history(tmp_path, records)

    summary = runner.write_provider_health_summary(tmp_path)

    assert summary["status"] == "PROVIDER_COOLDOWN_REQUIRED"
    assert summary["latest_status"] == "FAIL"
    assert summary["latest_control_results"] == {"A": "FAIL", "B": "PASS"}
    assert summary["complete_health_run_count"] == 2
    assert summary["consecutive_failing_runs"] == 1
    assert summary["legacy_ungrouped_control_count"] == 1


def test_health_summary_tracks_pass_fail_transitions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "results_dir", lambda: tmp_path / "results")
    records = []
    for run_id, status in (("one", "FAIL"), ("two", "PASS"), ("three", "PASS")):
        result_a = "FAIL" if status == "FAIL" else "PASS"
        records.extend(
            [_record(run_id, "A", result_a), _record(run_id, "B", "PASS"), _summary(run_id, status)]
        )
    _write_history(tmp_path, records)

    summary = runner.write_provider_health_summary(tmp_path)

    assert summary["status"] == "PASS"
    assert summary["full_pass_run_count"] == 2
    assert summary["full_fail_run_count"] == 1
    assert summary["consecutive_passing_runs"] == 2
    assert summary["consecutive_failing_runs"] == 0


def test_native_health_run_records_real_control_and_run_durations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "results_dir", lambda: tmp_path / "results")
    monkeypatch.setattr(runner, "git_sha", lambda: "f3f6d508")
    monkeypatch.setattr(
        runner,
        "native_control_row",
        lambda _root, _pair, _side, requested, label: {
            "control": label,
            "pair": _pair,
            "side": _side,
            "date": requested.isoformat(),
            "status": "PASS",
            "failure_category": "",
            "http_status": 200,
        },
    )

    payload = runner.run_native_health_controls(tmp_path)
    records = runner.read_jsonl_records(runner.native_health_history_path(tmp_path))

    assert payload["duration_ms"] >= 0
    assert len(records) == 3
    assert all(record["duration_ms"] >= 0 for record in records[:2])
    assert records[-1]["status"] == "PASS"
    assert records[-1]["control_results"] == {"A": "PASS", "B": "PASS"}


def test_native_health_watch_is_bounded_and_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "results_dir", lambda: tmp_path / "results")
    statuses = iter(["FAIL", "PASS", "PASS"])
    monkeypatch.setattr(
        runner, "run_native_health_controls", lambda _root: {"status": next(statuses)}
    )
    monkeypatch.setattr(
        runner,
        "write_provider_health_summary",
        lambda _root: (
            {"status": "PASS", "latest_status": "PASS"}
            if False
            else {"status": "PASS", "latest_status": "PASS"}
        ),
    )
    # The state is deliberately seeded as a previous failed run; resumed attempts must preserve it.
    runner.write_json(
        runner.native_health_watch_state_path(tmp_path),
        {
            "artifact_id": "A0R2_NATIVE_HEALTH_WATCH_STATE_V1",
            "attempts_completed": 1,
            "consecutive_passing_runs": 0,
            "history": [],
        },
    )

    result = runner.run_native_health_watch(
        tmp_path, max_attempts=2, interval_seconds=0, required_consecutive_passes=2
    )

    assert result["status"] == "NATIVE_HEALTH_READY"
    assert result["attempts_this_watch"] == 2
    assert (
        runner.read_json(runner.native_health_watch_state_path(tmp_path))["attempts_completed"] == 3
    )


def test_parity_panel_is_deterministic_and_queue_reuses_existing_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "results_dir", lambda: tmp_path / "results")
    for name in (
        "dual_transport_amendment.json",
        "stratified_parity_clarification.json",
        "dual_transport_parity_certification.json",
    ):
        runner.write_json(tmp_path / "results" / name, {"fixture": name})
    first = runner.freeze_parity_panel()
    second = runner.frozen_parity_panel()

    assert len(first["units"]) == 54
    assert first["panel_sha256"] == second["panel_sha256"]
    assert first["units"][0]["selection_class"] == "first_eligible_year_trading_interval"
    assert {unit["pair"] for unit in first["units"]} == set(runner.INSTRUMENTS)

    queue = runner.initialize_parity_queue(tmp_path)
    queue["units"][0]["overall_state"] = "COMPLETE"
    runner.write_json(runner.parity_queue_path(tmp_path), queue)

    resumed = runner.initialize_parity_queue(tmp_path)

    assert resumed["units"][0]["overall_state"] == "COMPLETE"
    assert runner.parity_queue_status(tmp_path)["state_distribution"]["PLANNED"] == 53
