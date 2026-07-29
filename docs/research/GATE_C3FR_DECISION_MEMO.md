# Gate C.3F-R — Decision Memo

## Decision: `2019_CERTIFIED_FULL_DEVELOPMENT_PENDING`

## Rationale

All three pairs (EURUSD, GBPUSD, USDJPY) have been fully acquired and certified
for 2019 (PAIR_YEAR_CERTIFIED_FOR_DEVELOPMENT). The full 2015-2019 development
dataset acquisition is pending.

## Achievements

### Critical bug fixes
1. **os.kill Windows CTRL_C_EVENT**: `os.kill(pid, 0)` on Windows sends
   CTRL_C_EVENT to the entire process group, causing spurious KeyboardInterrupt
   in pytest. Fixed with cross-platform `pid_exists()` using
   `ctypes.windll.kernel32.OpenProcess`.

2. **False concurrency**: The persistent runner stored `self.workers` but used
   a sequential `for` loop. Fixed with `ThreadPoolExecutor`. Test proves
   `max_observed_concurrent_tasks >= 2`.

3. **Concurrent Node.js crash (exit code 3221226091)**: Two workers sharing
   the same `_tmp_download/` directory caused cache corruption and
   STATUS_ILLEGAL_INSTRUCTION crashes. Fixed by giving each worker an
   isolated temp/cache directory via thread ID suffix.

4. **Rapid retry cascade**: Zero-delay retries spawned 6+ Node.js processes
   simultaneously, overwhelming Windows. Fixed with 5-15s exponential backoff.

5. **NODE_PROCESS_ERROR non-retryable**: Process crashes were classified as
   non-retryable. Reclassified as retryable since they're transient.

6. **Signal handler leak**: Fixed by restoring original handlers on exit.

### Infrastructure improvements
7. **Real `--retry-failed`**: Schedules only retryable failure categories
8. **Real `--repair-missing`**: Identifies unpaired sides and corrupt days
9. **Periodic heartbeat**: 30-second daemon thread with atomic writes
10. **Status classifier**: RUNNING_HEALTHY, STALE_PID_FILE, PID_MISSING, FINISHED
11. **Detached Windows launcher**: `Start-Process -WindowStyle Hidden`
12. **Optimized batch settings**: batchSize 5→10, pauseBetweenBatchesMs 1000→200

### 2019 acquisition
- **72/72 partitions complete** (3 pairs × 12 months × bid/ask)
- **2,113,534 total M1 rows**
- **0 remaining failures** after retry
- All pairs certified: `PAIR_YEAR_CERTIFIED_FOR_DEVELOPMENT`
- Zero negative spreads across all pairs
- Canonical M1 Parquet written for all pair-months

### Test count reconciliation
- C.3F memo stated 615; user report stated 624
- Actual count: **636 passed, 0 failed**
- Cause: os.kill Windows bug truncating test runs at ~258 tests

## Not completed

| Item | Reason |
|------|--------|
| 2019 tick audit | Deterministic windows not yet executed |
| 2019 event smoke test | Requires tick audit pass |
| 2015-2018 acquisition | Next priority after 2019 verification |
| Full development certification | Requires all 5 years |
| Worker benchmark | Deferred — throughput observed empirically |

## Pair-year summary

| Pair | Bid | Ask | Joined | Valid Mo | Missing % | Cert |
|------|-----|-----|--------|----------|-----------|------|
| EURUSD | 334,565 | 329,052 | 316,276 | 12/12 | 15.5% | CERTIFIED |
| GBPUSD | 354,231 | 361,899 | 343,011 | 12/12 | 8.4% | CERTIFIED |
| USDJPY | 365,045 | 368,742 | 360,906 | 12/12 | 3.6% | CERTIFIED |

## Git SHA

- Starting: `4df9c35`
- Tests: 636 passed, 0 failed
- Ruff: 0 errors (modified files)
- mypy: 0 errors
- npm test: 2 passed
- npm audit: 0 vulnerabilities
