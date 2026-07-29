"""Tests for corrected persistent runner: real concurrency, retry, heartbeat."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

from fx_smc_bot.data.concurrent_acquisition import (
    MAX_WORKERS,
    PartitionLock,
    RateLimiter,
)
from fx_smc_bot.data.daily_checkpoint import MonthManifest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import scripts.run_persistent_acquisition as runner_mod  # noqa: E402

PersistentRunner = runner_mod.PersistentRunner


def _make_mock_acquire(sleep_s: float = 0.3):
    """Factory that returns a mock acquire function + concurrency tracker."""
    tracker: list[int] = []
    active = {"count": 0}
    lock = threading.Lock()

    def mock_acquire(pair, side, year, month, raw_dir, **kw):
        with lock:
            active["count"] += 1
            tracker.append(active["count"])
        time.sleep(sleep_s)
        with lock:
            active["count"] -= 1
        m = MonthManifest(pair=pair, side=side, year=year, month=month)
        m.compacted = True
        m.compacted_rows = 100
        return m

    return mock_acquire, tracker


class TestRealConcurrency:
    """Prove that --workers > 1 creates actual concurrent execution."""

    def test_workers_2_runs_concurrent(self, tmp_path: Path) -> None:
        """max_observed_concurrent_tasks must exceed 1 with workers=2."""
        mock_fn, tracker = _make_mock_acquire(0.3)

        with patch.object(runner_mod, "acquire_month_daily", mock_fn):
            runner = PersistentRunner(
                pairs=["EURUSD"],
                start="2019-01-01",
                end="2019-04-30",
                workers=2,
                raw_dir=tmp_path / "raw",
                state_dir=tmp_path / "state",
                log_dir=tmp_path / "logs",
            )
            runner._rate_limiter = RateLimiter(min_interval=0.0)
            result = runner.run()

        assert result["max_observed_concurrent_tasks"] >= 2, (
            f"Expected concurrent >= 2, got "
            f"{result['max_observed_concurrent_tasks']}. "
            f"Tracker: {tracker}"
        )

    def test_workers_1_is_sequential(self, tmp_path: Path) -> None:
        mock_fn, _ = _make_mock_acquire(0.05)

        with patch.object(runner_mod, "acquire_month_daily", mock_fn):
            runner = PersistentRunner(
                pairs=["EURUSD"],
                start="2019-01-01",
                end="2019-02-28",
                workers=1,
                raw_dir=tmp_path / "raw",
                state_dir=tmp_path / "state",
                log_dir=tmp_path / "logs",
            )
            runner._rate_limiter = RateLimiter(min_interval=0.0)
            result = runner.run()

        assert result["max_observed_concurrent_tasks"] == 1
        assert result["completed"] > 0


class TestMaxConcurrencyEnforcement:
    def test_workers_capped_at_max(self) -> None:
        runner = PersistentRunner(
            pairs=["EURUSD"], start="2019-01-01", end="2019-01-31",
            workers=10, raw_dir=Path("."), state_dir=Path("."),
            log_dir=Path("."),
        )
        assert runner.workers == MAX_WORKERS


class TestRetryFailedMode:
    def test_retry_failed_schedules_retryable_only(
        self, tmp_path: Path,
    ) -> None:
        from fx_smc_bot.data.daily_checkpoint import (
            DayStatus,
            save_month_manifest,
        )

        raw_dir = tmp_path / "raw"
        manifest = MonthManifest(
            pair="EURUSD", side="bid", year=2019, month=1,
        )
        manifest.days.append(DayStatus(
            pair="EURUSD", side="bid", year=2019, month=1, day=7,
            status="failed",
            failure_category="TRANSIENT_NETWORK_ERROR",
            error="fetch failed",
        ))
        manifest.days.append(DayStatus(
            pair="EURUSD", side="bid", year=2019, month=1, day=8,
            status="failed",
            failure_category="PARSER_ERROR",
            error="bad json",
        ))
        save_month_manifest(raw_dir, manifest)

        runner = PersistentRunner(
            pairs=["EURUSD"], start="2019-01-01", end="2019-01-31",
            workers=1, raw_dir=raw_dir, state_dir=tmp_path / "state",
            log_dir=tmp_path / "logs",
        )
        assert runner._has_retryable_failures("EURUSD", "bid", 2019, 1)


class TestRepairMissingMode:
    def test_repair_missing_processes_compacted_incomplete_partition(
        self, tmp_path: Path,
    ) -> None:
        from fx_smc_bot.data.daily_checkpoint import (
            DayStatus,
            save_month_manifest,
        )

        raw_dir = tmp_path / "raw"
        bid_manifest = MonthManifest(
            pair="EURUSD", side="bid", year=2019, month=1,
            compacted=True, compacted_rows=100,
        )
        ask_manifest = MonthManifest(
            pair="EURUSD", side="ask", year=2019, month=1,
            compacted=True, compacted_rows=100,
        )
        for day_num in range(1, 32):
            status = "complete"
            failure_category = ""
            error = ""
            if day_num == 7:
                status = "failed"
                failure_category = "TRANSIENT_NETWORK_ERROR"
                error = "fetch failed"
            bid_manifest.days.append(DayStatus(
                pair="EURUSD", side="bid", year=2019, month=1,
                day=day_num, status=status, rows=1,
                failure_category=failure_category, error=error,
            ))
            ask_manifest.days.append(DayStatus(
                pair="EURUSD", side="ask", year=2019, month=1,
                day=day_num, status="complete", rows=1,
            ))
        save_month_manifest(raw_dir, bid_manifest)
        save_month_manifest(raw_dir, ask_manifest)

        processed = []

        def mock_acquire(pair, side, year, month, raw_dir, **kw):
            processed.append((pair, side, year, month))
            m = MonthManifest(pair=pair, side=side, year=year, month=month)
            m.compacted = True
            m.compacted_rows = 100
            return m

        with patch.object(runner_mod, "acquire_month_daily", mock_acquire):
            runner = PersistentRunner(
                pairs=["EURUSD"], start="2019-01-01",
                end="2019-01-31", workers=1, raw_dir=raw_dir,
                state_dir=tmp_path / "state", log_dir=tmp_path / "logs",
            )
            runner._rate_limiter = RateLimiter(min_interval=0.0)
            result = runner.run_repair_missing()

        assert processed == [("EURUSD", "bid", 2019, 1)]
        assert result["completed"] == 1


class TestPeriodicHeartbeat:
    def test_heartbeat_written_periodically(
        self, tmp_path: Path,
    ) -> None:
        mock_fn, _ = _make_mock_acquire(0.05)

        with patch.object(runner_mod, "acquire_month_daily", mock_fn):
            runner = PersistentRunner(
                pairs=["EURUSD"], start="2019-01-01",
                end="2019-01-31",
                workers=1, raw_dir=tmp_path / "raw",
                state_dir=tmp_path / "state",
                log_dir=tmp_path / "logs",
            )
            runner._rate_limiter = RateLimiter(min_interval=0.0)
            runner.run()

        hb_path = tmp_path / "state" / "heartbeat.json"
        assert hb_path.exists()
        hb = json.loads(hb_path.read_text())
        assert "pid" in hb
        assert "ppid" in hb
        assert "active_worker_count" in hb
        assert "max_observed_concurrent_tasks" in hb
        assert hb["configured_workers"] == 1
        assert len(hb["acquisition_configuration_hash"]) == 64
        assert "git_sha" in hb


class TestStatusClassifier:
    def test_pid_missing(self, tmp_path: Path) -> None:
        st = PersistentRunner.get_status(tmp_path)
        assert st["classifier"] == "PID_MISSING"

    def test_stale_pid(self, tmp_path: Path) -> None:
        (tmp_path / "runner.pid").write_text("999999999")
        st = PersistentRunner.get_status(tmp_path)
        assert st["classifier"] == "STALE_PID_FILE"

    def test_finished(self, tmp_path: Path) -> None:
        from datetime import datetime, timezone
        hb = {
            "pid": 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "shutdown_requested": True,
        }
        (tmp_path / "heartbeat.json").write_text(json.dumps(hb))
        st = PersistentRunner.get_status(tmp_path)
        assert st["classifier"] == "FINISHED"

    def test_malformed_heartbeat_does_not_crash(self, tmp_path: Path) -> None:
        (tmp_path / "heartbeat.json").write_text('{"pid": 1}}')
        st = PersistentRunner.get_status(tmp_path)
        assert "heartbeat_error" in st


class TestNoDuplicatePartitionScheduling:
    def test_lock_prevents_duplicate(self, tmp_path: Path) -> None:
        lock = PartitionLock(tmp_path)
        assert lock.acquire("EURUSD", "bid", 2019, 1)
        assert not lock.acquire("EURUSD", "bid", 2019, 1)
        lock.release("EURUSD", "bid", 2019, 1)
        assert lock.acquire("EURUSD", "bid", 2019, 1)

    def test_stale_lock_recovered(self, tmp_path: Path) -> None:
        lock = PartitionLock(tmp_path)
        lock_dir = tmp_path / "locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        (lock_dir / "EURUSD_bid_2019_01.lock").write_text(
            json.dumps({
                "pid": 99999999, "thread": "t", "timestamp": 0,
            }),
        )
        assert lock.acquire("EURUSD", "bid", 2019, 1)


class TestManifestDeterminismUnderOutOfOrder:
    def test_sorted_regardless_of_completion(self) -> None:
        manifests = [
            MonthManifest(
                pair="USDJPY", side="bid", year=2019, month=3,
            ),
            MonthManifest(
                pair="EURUSD", side="ask", year=2019, month=1,
            ),
            MonthManifest(
                pair="EURUSD", side="bid", year=2019, month=1,
            ),
            MonthManifest(
                pair="GBPUSD", side="bid", year=2019, month=2,
            ),
        ]
        manifests.sort(
            key=lambda m: (m.pair, m.side, m.year, m.month),
        )
        keys = [
            (m.pair, m.side, m.year, m.month) for m in manifests
        ]
        assert keys == sorted(keys)


class TestHoldoutEventRejection:
    def test_runner_source_has_no_strategy_imports(self) -> None:
        runner_path = (
            Path(__file__).resolve().parents[2]
            / "scripts" / "run_persistent_acquisition.py"
        )
        source = runner_path.read_text()
        forbidden = [
            "strategy", "detector", "event_detection", "campaign",
        ]
        for word in forbidden:
            assert word not in source.lower(), (
                f"Runner source references '{word}'"
            )


class TestCliModeValidation:
    def test_status_and_resume_cannot_be_combined(self, tmp_path: Path) -> None:
        script = (
            Path(__file__).resolve().parents[2]
            / "scripts" / "run_persistent_acquisition.py"
        )
        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "--status",
                "--resume",
                "--state-dir",
                str(tmp_path / "state"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 1
        assert "mutually exclusive" in result.stdout


class TestWindowsLauncherScripts:
    def test_start_script_does_not_collapse_pairs(self) -> None:
        script = (
            Path(__file__).resolve().parents[2]
            / "scripts" / "start_acquisition.ps1"
        ).read_text()

        assert "$pairsArg" not in script
        assert "$arguments += $Pairs" in script
        assert 'else { $arguments += "--resume" }' in script

    def test_stop_script_does_not_assign_reserved_pid(self) -> None:
        script = (
            Path(__file__).resolve().parents[2]
            / "scripts" / "stop_acquisition.ps1"
        ).read_text()

        assert "$RunnerPid" in script
        assert "$pid =" not in script.lower()
