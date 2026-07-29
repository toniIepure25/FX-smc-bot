# Gate C.3F-R — Development Dataset Report

## Status: INCOMPLETE

The full development dataset (2015-2019) has not yet been acquired.

## Acquisition priority (from Gate C.3F)

1. **Priority 1**: 2019 (event-smoke dataset) — IN PROGRESS
2. **Priority 2**: 2015-2018 (full development) — PENDING (after 2019 certification)
3. **Priority 3**: 2020-2022 (validation) — FUTURE
4. **Priority 4**: 2023-2025 (holdout completion) — FUTURE

## Infrastructure delivered

| Component | Status |
|-----------|--------|
| Genuine bounded concurrency | FIXED — ThreadPoolExecutor with max_observed_concurrent proof |
| Periodic heartbeat | IMPLEMENTED — 30s daemon thread |
| --retry-failed | IMPLEMENTED — schedules only retryable failures |
| --repair-missing | IMPLEMENTED — identifies unpaired sides and corrupt days |
| --status classifier | IMPLEMENTED — RUNNING_HEALTHY, STALE_HEARTBEAT, PID_MISSING, etc. |
| Cross-platform pid_exists | FIXED — ctypes on Windows, os.kill on Unix |
| Detached Windows launcher | CREATED — start_acquisition.ps1 with Start-Process |
| Signal handler restore | FIXED — original handlers restored on exit |
| os.kill Windows SIGINT bug | FIXED — eliminated CTRL_C_EVENT propagation |

## Holdout policy

- Development: 2015-01-01 through 2019-12-31
- Validation: 2020-01-01 through 2022-12-31
- Holdout: 2023-01-01 through 2025-12-31

Holdout access: download, checksum, structural quality only. No events, strategies, or PnL.
