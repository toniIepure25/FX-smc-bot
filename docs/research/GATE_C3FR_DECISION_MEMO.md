# Gate C.3F-R — Decision Memo

## Decision: `PARTIAL_DEVELOPMENT_DATA_NOT_CERTIFIED`

## Rationale

The corrected runner infrastructure is fully operational and verified, but the 2019 acquisition is still in progress. The gate cannot return a certified decision while data is actively being downloaded.

## Achievements

### Critical bug fixes
1. **os.kill Windows CTRL_C_EVENT**: `os.kill(pid, 0)` on Windows sends CTRL_C_EVENT to the entire process group, causing spurious KeyboardInterrupt in pytest (test count stuck at 258/636) and potential data corruption. Fixed with cross-platform `pid_exists()` using `ctypes.windll.kernel32.OpenProcess`.

2. **False concurrency**: The persistent runner stored `self.workers = min(workers, 4)` but processed partitions in a sequential `for` loop. Fixed by integrating `ThreadPoolExecutor` directly into `_process_partition`. Test proves `max_observed_concurrent_tasks >= 2`.

3. **Signal handler leak**: `signal.signal(SIGINT, handler)` persisted after runner exit, corrupting subsequent signal handling. Fixed by restoring original handlers.

### Infrastructure improvements
4. **Real `--retry-failed`**: Schedules only partitions with retryable failure categories
5. **Real `--repair-missing`**: Identifies unpaired bid/ask sides and corrupt days
6. **Periodic heartbeat**: 30-second daemon thread with atomic writes
7. **Status classifier**: RUNNING_HEALTHY, RUNNING_STALE_HEARTBEAT, PID_MISSING, STALE_PID_FILE, FINISHED
8. **Detached Windows launcher**: `start_acquisition.ps1` using `Start-Process -WindowStyle Hidden`

### Test count reconciliation
- C.3F memo stated 615; user report stated 624
- Actual count: **636 passed, 0 failed**
- Discrepancy cause: os.kill Windows bug truncating test runs at ~258 tests

## Not completed

| Item | Reason |
|------|--------|
| 2019 acquisition | Network I/O bound (~72 partitions, hours required) |
| 2019 certification | Requires completed acquisition |
| 2019 tick audit | Requires completed acquisition |
| 2019 event smoke test | Requires certification |
| 2015-2018 acquisition | Requires 2019 certification first |
| Full development certification | Requires all 5 years |
| Worker benchmark | Requires uncached units |

## How to continue

```powershell
# Check status
.\scripts\status_acquisition.ps1

# If finished, retry failures
python scripts/run_persistent_acquisition.py --retry-failed --state-dir data/acquisition_state

# Repair missing sides
python scripts/run_persistent_acquisition.py --repair-missing --pairs EURUSD GBPUSD USDJPY --start 2019-01-01 --end 2019-12-31 --state-dir data/acquisition_state

# Launch detached for long runs
.\scripts\start_acquisition.ps1 -Start "2015-01-01" -End "2019-12-31"
```

## Git SHA

- Starting: `4df9c35`
- Tests: 636 passed, 0 failed
- Ruff: 0 errors (modified files)
- mypy: 0 errors
- npm test: 2 passed
- npm audit: 0 vulnerabilities
