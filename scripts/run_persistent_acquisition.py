"""Persistent acquisition runner with PID files, heartbeat, and graceful termination.

Usage:
    python scripts/run_persistent_acquisition.py \\
      --pairs EURUSD GBPUSD USDJPY \\
      --start 2019-01-01 --end 2019-12-31 \\
      --workers 2 --resume \\
      --log-dir logs/acquisition --state-dir data/acquisition_state

    python scripts/run_persistent_acquisition.py --status \\
      --state-dir data/acquisition_state

    python scripts/run_persistent_acquisition.py --retry-failed \\
      --state-dir data/acquisition_state
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fx_smc_bot.data.daily_checkpoint import (  # noqa: E402
    acquire_month_daily,
    load_month_manifest,
)
from fx_smc_bot.data.dukascopy_node_provider import (  # noqa: E402
    _month_range,
)

logger = logging.getLogger("persistent_acquisition")


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
        self.workers = min(workers, 4)
        self.raw_dir = raw_dir
        self.state_dir = state_dir
        self.log_dir = log_dir
        self.resume = resume
        self._shutdown = False
        self._current_partition: str = ""

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
                pid = int(pid_path.read_text().strip())
                os.kill(pid, 0)
                return True
            except (OSError, ValueError):
                pid_path.unlink(missing_ok=True)
        return False

    def _write_pid(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._pid_path().write_text(str(os.getpid()))

    def _write_heartbeat(self) -> None:
        hb = {
            "pid": os.getpid(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "current_partition": self._current_partition,
            "shutdown_requested": self._shutdown,
        }
        tmp = self._heartbeat_path().with_suffix(".tmp")
        tmp.write_text(json.dumps(hb, indent=2))
        os.replace(str(tmp), str(self._heartbeat_path()))

    def _write_progress(self, progress: dict) -> None:
        tmp = self._progress_path().with_suffix(".tmp")
        tmp.write_text(json.dumps(progress, indent=2))
        os.replace(str(tmp), str(self._progress_path()))

    def _signal_handler(self, signum: int, frame: object) -> None:
        logger.warning(f"Signal {signum} received, finishing current partition...")
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

    def run(self) -> dict:
        if self._check_existing():
            logger.error("Another runner is already active")
            return {"error": "another runner active"}

        self._setup_signals()
        self._write_pid()
        self.log_dir.mkdir(parents=True, exist_ok=True)

        log_file = (
            self.log_dir
            / f"acquisition_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.log"
        )
        fh = logging.FileHandler(str(log_file))
        fh.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s"),
        )
        logging.getLogger().addHandler(fh)

        partitions = self._build_partition_list()
        total = len(partitions)
        completed = 0
        failed = 0
        skipped = 0

        logger.info(
            f"Starting acquisition: {total} partitions, "
            f"pairs={self.pairs}, range={self.start} to {self.end}",
        )

        for i, (pair, side, year, month) in enumerate(partitions):
            if self._shutdown:
                logger.warning("Shutdown requested, exiting gracefully")
                break

            self._current_partition = f"{pair}/{side}/{year}-{month:02d}"
            self._write_heartbeat()

            if self.resume and self._is_partition_complete(
                pair, side, year, month,
            ):
                skipped += 1
                continue

            logger.info(f"[{i + 1}/{total}] Acquiring {self._current_partition}")

            try:
                manifest = acquire_month_daily(
                    pair, side, year, month, self.raw_dir,
                )
                if manifest.compacted:
                    completed += 1
                    logger.info(
                        f"  Completed: {manifest.compacted_rows} rows"
                    )
                else:
                    failed += 1
                    logger.warning("  Not fully compacted")
            except Exception as e:
                failed += 1
                logger.error(f"  Error: {e}")

            progress = {
                "total": total,
                "processed": i + 1,
                "completed": completed,
                "skipped": skipped,
                "failed": failed,
                "current": self._current_partition,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self._write_progress(progress)

        self._pid_path().unlink(missing_ok=True)
        self._current_partition = ""
        self._write_heartbeat()

        summary = {
            "total_partitions": total,
            "completed": completed,
            "skipped": skipped,
            "failed": failed,
            "shutdown_requested": self._shutdown,
            "log_file": str(log_file),
        }
        self._write_progress(summary)
        logger.info(f"Acquisition finished: {json.dumps(summary)}")
        return summary

    @staticmethod
    def get_status(state_dir: Path) -> dict:
        hb_path = state_dir / "heartbeat.json"
        prog_path = state_dir / "progress.json"
        pid_path = state_dir / "runner.pid"

        status: dict = {"running": False}

        if pid_path.exists():
            try:
                pid = int(pid_path.read_text().strip())
                os.kill(pid, 0)
                status["running"] = True
                status["pid"] = pid
            except (OSError, ValueError):
                status["stale_pid"] = True

        if hb_path.exists():
            status["heartbeat"] = json.loads(hb_path.read_text())
        if prog_path.exists():
            status["progress"] = json.loads(prog_path.read_text())

        return status


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Persistent FX data acquisition runner",
    )
    parser.add_argument("--pairs", nargs="+", default=["EURUSD", "GBPUSD", "USDJPY"])
    parser.add_argument("--start", default="2019-01-01")
    parser.add_argument("--end", default="2019-12-31")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--log-dir", default="logs/acquisition")
    parser.add_argument("--state-dir", default="data/acquisition_state")
    parser.add_argument(
        "--raw-dir", default="data/raw/dukascopy-node",
    )
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    state_dir = Path(args.state_dir)

    if args.status:
        status = PersistentRunner.get_status(state_dir)
        print(json.dumps(status, indent=2))
        return

    runner = PersistentRunner(
        pairs=args.pairs,
        start=args.start,
        end=args.end,
        workers=args.workers,
        raw_dir=Path(args.raw_dir),
        state_dir=state_dir,
        log_dir=Path(args.log_dir),
        resume=args.resume,
    )
    result = runner.run()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
