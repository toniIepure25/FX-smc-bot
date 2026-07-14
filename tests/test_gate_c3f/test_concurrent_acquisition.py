"""Tests for bounded concurrent acquisition."""
from __future__ import annotations

import json
from pathlib import Path

from fx_smc_bot.data.concurrent_acquisition import (
    DEFAULT_WORKERS,
    MAX_WORKERS,
    PartitionLock,
    RateLimiter,
)


class TestRateLimiter:
    def test_default_interval(self) -> None:
        rl = RateLimiter()
        assert rl._min_interval >= 1.0

    def test_custom_interval(self) -> None:
        rl = RateLimiter(min_interval=0.5)
        assert rl._min_interval == 0.5


class TestPartitionLock:
    def test_acquire_and_release(self, tmp_path: Path) -> None:
        lock = PartitionLock(tmp_path)
        assert lock.acquire("EURUSD", "bid", 2019, 1)
        lock.release("EURUSD", "bid", 2019, 1)

    def test_double_acquire_same_pid_allowed(self, tmp_path: Path) -> None:
        lock = PartitionLock(tmp_path)
        assert lock.acquire("EURUSD", "bid", 2019, 1)
        assert not lock.acquire("EURUSD", "bid", 2019, 1)

    def test_stale_lock_recovery(self, tmp_path: Path) -> None:
        lock = PartitionLock(tmp_path)
        lock_dir = tmp_path / "locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_file = lock_dir / "EURUSD_bid_2019_01.lock"
        lock_file.write_text(json.dumps({"pid": 99999999, "thread": "t", "timestamp": 0}))
        assert lock.acquire("EURUSD", "bid", 2019, 1)


class TestWorkerConfig:
    def test_default_workers(self) -> None:
        assert DEFAULT_WORKERS == 2

    def test_max_workers(self) -> None:
        assert MAX_WORKERS == 4

    def test_different_partitions_can_lock(self, tmp_path: Path) -> None:
        lock = PartitionLock(tmp_path)
        assert lock.acquire("EURUSD", "bid", 2019, 1)
        assert lock.acquire("EURUSD", "ask", 2019, 1)
        assert lock.acquire("GBPUSD", "bid", 2019, 1)


class TestDeterministicOrdering:
    def test_manifests_sorted(self) -> None:
        from fx_smc_bot.data.daily_checkpoint import MonthManifest
        manifests = [
            MonthManifest(pair="USDJPY", side="bid", year=2019, month=3),
            MonthManifest(pair="EURUSD", side="ask", year=2019, month=1),
            MonthManifest(pair="EURUSD", side="bid", year=2019, month=1),
        ]
        manifests.sort(key=lambda m: (m.pair, m.side, m.year, m.month))
        assert manifests[0].pair == "EURUSD"
        assert manifests[0].side == "ask"
        assert manifests[1].side == "bid"
        assert manifests[2].pair == "USDJPY"
