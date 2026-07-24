"""Bounded concurrent acquisition with rate limiting.

Provides a worker pool for parallel data acquisition with:
- Configurable worker count (default 2, max 4)
- Shared rate limiter
- Lock files preventing duplicate work
- Deterministic final manifests regardless of completion order
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from fx_smc_bot.data.daily_checkpoint import (
    MonthManifest,
    acquire_month_daily,
    load_month_manifest,
    normalize_month_manifest_for_repair,
)

logger = logging.getLogger(__name__)


def pid_exists(pid: int) -> bool:
    """Check if a process with the given PID is running (cross-platform)."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        process_query = 0x1000  # PROCESS_QUERY_LIMITED_INFORMATION
        handle = kernel32.OpenProcess(process_query, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False

DEFAULT_WORKERS = 2
MAX_WORKERS = 4
MIN_REQUEST_INTERVAL_S = 1.0


@dataclass(slots=True)
class WorkerBenchmark:
    """Benchmark results for a worker configuration."""
    workers: int
    partitions_attempted: int
    partitions_completed: int
    partitions_failed: int
    total_seconds: float
    throughput_per_hour: float
    peak_memory_mb: float = 0.0

    def to_dict(self) -> dict:
        return {
            "workers": self.workers,
            "partitions_attempted": self.partitions_attempted,
            "partitions_completed": self.partitions_completed,
            "partitions_failed": self.partitions_failed,
            "total_seconds": round(self.total_seconds, 1),
            "throughput_per_hour": round(self.throughput_per_hour, 2),
            "peak_memory_mb": round(self.peak_memory_mb, 1),
        }


class RateLimiter:
    """Thread-safe rate limiter for provider-friendly pacing."""
    def __init__(self, min_interval: float = MIN_REQUEST_INTERVAL_S):
        self._min_interval = min_interval
        self._lock = threading.Lock()
        self._last_request = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_request = time.monotonic()


class PartitionLock:
    """File-based lock to prevent duplicate workers on same partition."""
    def __init__(self, state_dir: Path):
        self._dir = state_dir / "locks"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _lock_path(self, pair: str, side: str, year: int, month: int) -> Path:
        return self._dir / f"{pair}_{side}_{year}_{month:02d}.lock"

    def acquire(self, pair: str, side: str, year: int, month: int) -> bool:
        path = self._lock_path(pair, side, year, month)
        if path.exists():
            try:
                lock_data = json.loads(path.read_text())
                lock_pid = lock_data.get("pid", 0)
                if pid_exists(lock_pid):
                    return False
            except (ValueError, json.JSONDecodeError):
                pass
            path.unlink(missing_ok=True)
        path.write_text(json.dumps({
            "pid": os.getpid(),
            "thread": threading.current_thread().name,
            "timestamp": time.time(),
        }))
        return True

    def release(self, pair: str, side: str, year: int, month: int) -> None:
        self._lock_path(pair, side, year, month).unlink(missing_ok=True)


def acquire_concurrent(
    partitions: list[tuple[str, str, int, int]],
    raw_dir: Path,
    state_dir: Path,
    workers: int = DEFAULT_WORKERS,
    rate_limiter: RateLimiter | None = None,
) -> list[MonthManifest]:
    """Acquire partitions concurrently with bounded workers.

    Args:
        partitions: List of (pair, side, year, month) tuples
        raw_dir: Raw data directory
        state_dir: State directory for locks
        workers: Number of concurrent workers (capped at MAX_WORKERS)
        rate_limiter: Optional shared rate limiter
    """
    workers = min(workers, MAX_WORKERS)
    if rate_limiter is None:
        rate_limiter = RateLimiter()
    lock = PartitionLock(state_dir)

    results: list[MonthManifest] = []
    results_lock = threading.Lock()

    def _worker(pair: str, side: str, year: int, month: int) -> MonthManifest | None:
        if not lock.acquire(pair, side, year, month):
            logger.warning(
                f"Skipping {pair}/{side}/{year}-{month:02d}: locked by another worker"
            )
            return None

        try:
            existing = load_month_manifest(raw_dir, pair, side, year, month)
            if existing:
                existing = normalize_month_manifest_for_repair(
                    raw_dir, existing,
                )
            if existing and existing.compacted and existing.compacted_rows > 0:
                return existing

            rate_limiter.wait()
            manifest = acquire_month_daily(pair, side, year, month, raw_dir)
            return manifest
        finally:
            lock.release(pair, side, year, month)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_worker, *p): p for p in partitions
        }

        for future in as_completed(futures):
            partition = futures[future]
            try:
                manifest = future.result()
                if manifest is not None:
                    with results_lock:
                        results.append(manifest)
            except Exception as e:
                logger.error(f"Worker error for {partition}: {e}")

    results.sort(key=lambda m: (m.pair, m.side, m.year, m.month))
    return results
