# Gate C.3F-R — Runner Audit Report

## Starting state

Two non-persistent acquisition processes found at gate start:
- PID 27012: Old C.3R-era `download_partition` loop, Cursor-attached
- PID 10776: C.3F daily checkpoint loop, Cursor-attached

Neither process had:
- A PID file
- A heartbeat file
- Signal handlers for graceful shutdown
- Any mechanism to survive terminal closure

## Defects identified

### 1. False concurrency

`run_persistent_acquisition.py` stored `self.workers = min(workers, 4)` but the `run()` method processed partitions in a sequential `for` loop. The `concurrent_acquisition.py` module provided `ThreadPoolExecutor`-based acquisition via `acquire_concurrent()`, but the persistent runner never used it.

### 2. `--retry-failed` not implemented

`argparse` defined `--retry-failed` but no code path executed when the flag was set.

### 3. Non-periodic heartbeat

Heartbeat was written only between partition transitions inside the sequential loop. No background thread provided periodic status updates.

### 4. `os.kill(pid, 0)` Windows bug

On Windows, `os.kill(pid, 0)` does not merely check process existence — it sends `CTRL_C_EVENT` to the entire process group. This caused `KeyboardInterrupt` exceptions that terminated pytest at test 258/636 and could crash the runner itself.

### 5. Status format incomplete

`get_status()` returned `{"running": bool}` without health classification (stale heartbeat, finished, failed).

## Fixes applied

| Issue | Fix |
|-------|-----|
| Sequential execution | `ThreadPoolExecutor` in `_process_partition`, `_max_concurrent` tracking |
| Retry not working | `run_retry_failed()`, `run_repair_missing()` with distinct scheduling |
| Heartbeat | Daemon thread with 30s interval, atomic JSON writes |
| `os.kill` bug | Cross-platform `pid_exists()` using `ctypes.windll.kernel32.OpenProcess` on Windows |
| Status | Classifier: RUNNING_HEALTHY, RUNNING_STALE_HEARTBEAT, PID_MISSING, STALE_PID_FILE, FINISHED |
| Signal handlers | Restored to original on runner exit |
| Detached launch | `start_acquisition.ps1` using `Start-Process -WindowStyle Hidden` |

## Concurrency proof

Test `TestRealConcurrency::test_workers_2_runs_concurrent` asserts `max_observed_concurrent_tasks >= 2` when `--workers 2`. The test passed.

## Test count reconciliation

| Source | Count |
|--------|-------|
| C.3F memo | 615 |
| C.3F user report | 624 |
| C.3F-R actual | 636 |

The discrepancy was caused by:
1. `KeyboardInterrupt` from `os.kill` bug truncating test runs at test ~258
2. Different test runs observing different subsets before the interrupt
3. 12 new tests added in C.3F-R
