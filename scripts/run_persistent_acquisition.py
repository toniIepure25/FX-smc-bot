"""Persistent acquisition runner with real bounded concurrency.

Usage:
    python scripts/run_persistent_acquisition.py \\
      --pairs EURUSD GBPUSD USDJPY \\
      --start 2019-01-01 --end 2019-12-31 \\
      --workers 2 --resume \\
      --log-dir logs/acquisition --state-dir data/acquisition_state

    python scripts/run_persistent_acquisition.py --status \\
      --state-dir data/acquisition_state

    python scripts/run_persistent_acquisition.py --retry-failed \\
      --pairs EURUSD GBPUSD USDJPY \\
      --start 2019-01-01 --end 2019-12-31 \\
      --state-dir data/acquisition_state
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fx_smc_bot.data.concurrent_acquisition import (  # noqa: E402
    MAX_WORKERS,
    PartitionLock,
    RateLimiter,
    pid_exists,
)
from fx_smc_bot.data.daily_checkpoint import (  # noqa: E402
    acquire_month_daily,
    find_missing_days,
    load_month_manifest,
)
from fx_smc_bot.data.dukascopy_node_provider import (  # noqa: E402
    _month_range,
)
from fx_smc_bot.data.failure_categories import (  # noqa: E402
    FailureCategory,
    is_retryable,
)

logger = logging.getLogger("persistent_acquisition")

HEARTBEAT_INTERVAL_S = 30


class PersistentRunner:
    def __init__(
        self,
        pairs: list[str],
        start: str,
        end: str,
        workers: int,
        raw_dir: Path,
        state_dir: Path,
        log_dir: Path,
        resume: bool = False,
    ):
        self.pairs = pairs
        self.start = start
        self.end = end
        self.workers = max(1, min(workers, MAX_WORKERS))
        self.raw_dir = raw_dir
        self.state_dir = state_dir
        self.log_dir = log_dir
        self.resume = resume
        self._shutdown = False
        self._lock = threading.Lock()
        self._active_tasks: list[str] = []
        self._orig_sigint = signal.getsignal(signal.SIGINT)
        self._orig_sigterm = signal.getsignal(signal.SIGTERM)
        self._completed = 0
        self._failed = 0
        self._skipped = 0
        self._total_rows = 0
        self._max_concurrent = 0
        self._start_time = ""
        self._last_error = ""
        self._last_checkpoint = ""
        self._heartbeat_thread: threading.Thread | None = None
        self._rate_limiter = RateLimiter()
        self._partition_lock = PartitionLock(state_dir)

    def _pid_path(self) -> Path:
        return self.state_dir / "runner.pid"

    def _heartbeat_path(self) -> Path:
        return self.state_dir / "heartbeat.json"

    def _progress_path(self) -> Path:
        return self.state_dir / "progress.json"

    def _check_existing(self) -> bool:
        pid_path = self._pid_path()
        if pid_path.exists():
            try:
                existing_pid = int(pid_path.read_text().strip())
                if pid_exists(existing_pid):
                    return True
            except ValueError:
                pass
            pid_path.unlink(missing_ok=True)
        return False

    def _write_pid(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._pid_path().write_text(str(os.getpid()))

    def _write_heartbeat(self) -> None:
        with self._lock:
            active = list(self._active_tasks)
            concurrent = len(active)
            if concurrent > self._max_concurrent:
                self._max_concurrent = concurrent
        hb = {
            "pid": os.getpid(),
            "ppid": os.getppid(),
            "process_start_time": self._start_time,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "active_tasks": active,
            "active_worker_count": concurrent,
            "max_observed_concurrent_tasks": self._max_concurrent,
            "completed": self._completed,
            "failed": self._failed,
            "skipped": self._skipped,
            "total_rows": self._total_rows,
            "last_checkpoint": self._last_checkpoint,
            "last_error": self._last_error,
            "shutdown_requested": self._shutdown,
            "workers_configured": self.workers,
        }
        tmp = self._heartbeat_path().with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(hb, indent=2))
            os.replace(str(tmp), str(self._heartbeat_path()))
        except OSError:
            pass

    def _heartbeat_loop(self) -> None:
        while not self._shutdown:
            self._write_heartbeat()
            for _ in range(HEARTBEAT_INTERVAL_S):
                if self._shutdown:
                    break
                time.sleep(1)

    def _start_heartbeat(self) -> None:
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True,
        )
        self._heartbeat_thread.start()

    def _write_progress(self, progress: dict) -> None:
        tmp = self._progress_path().with_suffix(".tmp")
        tmp.write_text(json.dumps(progress, indent=2))
        os.replace(str(tmp), str(self._progress_path()))

    def _signal_handler(self, signum: int, frame: object) -> None:
        logger.warning(
            f"Signal {signum} received, finishing active tasks...",
        )
        self._shutdown = True

    def _setup_signals(self) -> None:
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _build_partition_list(self) -> list[tuple[str, str, int, int]]:
        start_dt = datetime.strptime(self.start, "%Y-%m-%d")
        end_dt = datetime.strptime(self.end, "%Y-%m-%d")
        partitions = []
        for pair in self.pairs:
            for year, month in _month_range(
                start_dt.year, start_dt.month,
                end_dt.year, end_dt.month,
            ):
                for side in ("bid", "ask"):
                    partitions.append((pair, side, year, month))
        return partitions

    def _is_partition_complete(
        self, pair: str, side: str, year: int, month: int,
    ) -> bool:
        manifest = load_month_manifest(
            self.raw_dir, pair, side, year, month,
        )
        return manifest is not None and manifest.compacted

    def _has_retryable_failures(
        self, pair: str, side: str, year: int, month: int,
    ) -> bool:
        manifest = load_month_manifest(
            self.raw_dir, pair, side, year, month,
        )
        if manifest is None:
            return False
        for d in manifest.days:
            if d.status == "failed" and d.failure_category:
                try:
                    cat = FailureCategory(d.failure_category)
                    if is_retryable(cat):
                        return True
                except ValueError:
                    pass
        return False

    def _process_partition(
        self, pair: str, side: str, year: int, month: int,
    ) -> bool:
        tag = f"{pair}/{side}/{year}-{month:02d}"
        if not self._partition_lock.acquire(pair, side, year, month):
            logger.warning(f"Skipping {tag}: locked")
            return False

        with self._lock:
            self._active_tasks.append(tag)
            concurrent = len(self._active_tasks)
            if concurrent > self._max_concurrent:
                self._max_concurrent = concurrent

        try:
            manifest = acquire_month_daily(
                pair, side, year, month, self.raw_dir,
            )
            with self._lock:
                if manifest.compacted:
                    self._completed += 1
                    self._total_rows += manifest.compacted_rows
                    self._last_checkpoint = tag
                    logger.info(f"  {tag}: {manifest.compacted_rows} rows")
                    return True
                else:
                    self._failed += 1
                    return False
        except Exception as e:
            with self._lock:
                self._failed += 1
                self._last_error = f"{tag}: {e}"
            logger.error(f"  {tag} error: {e}")
            return False
        finally:
            self._partition_lock.release(pair, side, year, month)
            with self._lock:
                if tag in self._active_tasks:
                    self._active_tasks.remove(tag)

    def run(
        self,
        partitions: list[tuple[str, str, int, int]] | None = None,
    ) -> dict:
        if self._check_existing():
            logger.error("Another runner is already active")
            return {"error": "another runner active"}

        self._setup_signals()
        self._write_pid()
        self._start_time = datetime.now(timezone.utc).isoformat()
        self.log_dir.mkdir(parents=True, exist_ok=True)

        log_file = (
            self.log_dir
            / f"acq_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.log"
        )
        fh = logging.FileHandler(str(log_file))
        fh.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s"),
        )
        logging.getLogger().addHandler(fh)

        if partitions is None:
            partitions = self._build_partition_list()

        work: list[tuple[str, str, int, int]] = []
        for p in partitions:
            if self._is_partition_complete(*p):
                self._skipped += 1
            else:
                work.append(p)

        total = len(work) + self._skipped
        logger.info(
            f"Runner: {total} partitions ({len(work)} to process, "
            f"{self._skipped} skipped), workers={self.workers}",
        )

        self._start_heartbeat()

        if self.workers == 1:
            for p in work:
                if self._shutdown:
                    break
                self._process_partition(*p)
        else:
            with ThreadPoolExecutor(
                max_workers=self.workers,
            ) as executor:
                futures = {}
                for p in work:
                    if self._shutdown:
                        break
                    f = executor.submit(self._process_partition, *p)
                    futures[f] = p

                for future in as_completed(futures):
                    if self._shutdown:
                        executor.shutdown(wait=False, cancel_futures=True)
                        break
                    try:
                        future.result()
                    except Exception as e:
                        logger.error(f"Future error: {e}")

        self._shutdown = True
        self._write_heartbeat()
        self._pid_path().unlink(missing_ok=True)
        signal.signal(signal.SIGINT, self._orig_sigint)
        signal.signal(signal.SIGTERM, self._orig_sigterm)

        summary = {
            "total_partitions": total,
            "completed": self._completed,
            "skipped": self._skipped,
            "failed": self._failed,
            "total_rows": self._total_rows,
            "max_observed_concurrent_tasks": self._max_concurrent,
            "workers_configured": self.workers,
            "log_file": str(log_file),
        }
        self._write_progress(summary)
        logger.info(f"Finished: {json.dumps(summary)}")
        return summary

    def run_retry_failed(self) -> dict:
        """Re-run only retryable failed partitions."""
        all_partitions = self._build_partition_list()
        retryable: list[tuple[str, str, int, int]] = []
        for pair, side, year, month in all_partitions:
            if self._has_retryable_failures(pair, side, year, month):
                retryable.append((pair, side, year, month))

        logger.info(f"Retry-failed: {len(retryable)} partitions with retryable failures")
        if not retryable:
            return {"retryable_partitions": 0}
        return self.run(partitions=retryable)

    def run_repair_missing(self) -> dict:
        """Repair missing bid/ask sides and corrupt days."""
        all_partitions = self._build_partition_list()
        to_repair: list[tuple[str, str, int, int]] = []
        for pair, side, year, month in all_partitions:
            missing = find_missing_days(
                self.raw_dir, pair, side, year, month,
            )
            if missing:
                to_repair.append((pair, side, year, month))

        logger.info(f"Repair-missing: {len(to_repair)} partitions need repair")
        if not to_repair:
            return {"partitions_needing_repair": 0}
        return self.run(partitions=to_repair)

    @staticmethod
    def get_status(state_dir: Path, raw_dir: Path | None = None) -> dict:
        hb_path = state_dir / "heartbeat.json"
        prog_path = state_dir / "progress.json"
        pid_path = state_dir / "runner.pid"

        status: dict = {"classifier": "PID_MISSING"}
        pid_alive = False

        if pid_path.exists():
            try:
                stored_pid = int(pid_path.read_text().strip())
                if pid_exists(stored_pid):
                    pid_alive = True
                    status["pid"] = stored_pid
                else:
                    status["classifier"] = "STALE_PID_FILE"
            except ValueError:
                status["classifier"] = "STALE_PID_FILE"

        if hb_path.exists():
            hb = json.loads(hb_path.read_text())
            status["heartbeat"] = hb
            hb_ts = hb.get("timestamp", "")
            if hb_ts:
                try:
                    hb_dt = datetime.fromisoformat(hb_ts)
                    age_s = (
                        datetime.now(timezone.utc) - hb_dt
                    ).total_seconds()
                    status["heartbeat_age_seconds"] = round(age_s, 1)
                    if pid_alive:
                        if age_s < HEARTBEAT_INTERVAL_S * 3:
                            status["classifier"] = "RUNNING_HEALTHY"
                        else:
                            status["classifier"] = "RUNNING_STALE_HEARTBEAT"
                    elif hb.get("shutdown_requested"):
                        status["classifier"] = "FINISHED"
                except (ValueError, TypeError):
                    pass

        if prog_path.exists():
            status["progress"] = json.loads(prog_path.read_text())

        if not pid_path.exists() and not hb_path.exists():
            status["classifier"] = "PID_MISSING"

        return status


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Persistent FX data acquisition runner",
    )
    parser.add_argument(
        "--pairs", nargs="+",
        default=["EURUSD", "GBPUSD", "USDJPY"],
    )
    parser.add_argument("--start", default="2019-01-01")
    parser.add_argument("--end", default="2019-12-31")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--repair-missing", action="store_true")
    parser.add_argument("--log-dir", default="logs/acquisition")
    parser.add_argument("--state-dir", default="data/acquisition_state")
    parser.add_argument(
        "--raw-dir", default="data/raw/dukascopy-node",
    )
    parser.add_argument("--status", action="store_true")

    args = parser.parse_args()

    modes = sum([
        args.status, args.resume, args.retry_failed, args.repair_missing,
    ])
    if modes > 1 and not args.status:
        print("ERROR: --resume, --retry-failed, --repair-missing are mutually exclusive")
        sys.exit(1)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    state_dir = Path(args.state_dir)
    raw_dir = Path(args.raw_dir)

    if args.status:
        st = PersistentRunner.get_status(state_dir, raw_dir)
        print(json.dumps(st, indent=2))
        return

    runner = PersistentRunner(
        pairs=args.pairs,
        start=args.start,
        end=args.end,
        workers=args.workers,
        raw_dir=raw_dir,
        state_dir=state_dir,
        log_dir=Path(args.log_dir),
        resume=args.resume or args.retry_failed or args.repair_missing,
    )

    if args.retry_failed:
        result = runner.run_retry_failed()
    elif args.repair_missing:
        result = runner.run_repair_missing()
    else:
        result = runner.run()

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
