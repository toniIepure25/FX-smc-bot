# Gate C.3F — Acquisition Reliability Report

## Architecture Changes

### Daily Checkpoints (NEW)
Each day is downloaded, validated, and persisted atomically before moving
to the next. Monthly compaction only occurs after all expected trading
days reach a terminal status. This eliminates the Gate C.3R failure mode
where a single failed day would require re-downloading the entire month.

### Failure Categories (NEW)
Every acquisition outcome is classified into one of 11 explicit categories.
Weekend and holiday emptiness are classified as `MARKET_CLOSED_WEEKEND`
and `MARKET_CLOSED_HOLIDAY` respectively — never as failures. Only
retryable categories trigger automatic retries.

### Targeted Repair (NEW)
The `--repair-missing` CLI option identifies and retrieves only missing
or corrupt day+side combinations without re-downloading verified days.

### Persistent Runner (NEW)
`scripts/run_persistent_acquisition.py` provides:
- PID file preventing duplicate runners
- Heartbeat file updated each partition
- Structured progress JSON
- Graceful SIGINT/SIGTERM handling
- Resume capability via `--resume` flag
- Status query via `--status` flag

### Bounded Concurrency (NEW)
`concurrent_acquisition.py` provides a thread-pool worker model with:
- Default 2 workers, maximum 4
- Shared rate limiter (minimum 1s between requests)
- File-based partition locks with stale-lock recovery
- Deterministic manifest ordering regardless of completion order

## Reliability Improvements Over Gate C.3R

| Aspect | C.3R | C.3F |
|--------|------|------|
| Checkpoint granularity | Month | Day |
| Recovery after crash | Re-download entire month | Resume from last completed day |
| Failure classification | Generic error string | 11 explicit categories |
| Weekend handling | Counted as failed retry | `MARKET_CLOSED_WEEKEND` |
| Repair scope | Full re-acquisition | Missing days only |
| Process persistence | Background shell (lost on close) | PID + heartbeat files |
| Memory model | Accumulate full month in list | Process one day, release |
| Concurrency | Sequential | Bounded worker pool |

## Known Limitations

1. **Network reliability** — the Dukascopy CDN remains the bottleneck;
   transient `fetch failed` errors occur at ~20-40% of requests.
2. **Throughput** — approximately 1-3 minutes per day per side, depending
   on network conditions and retry count.
3. **Full development acquisition** — 3 pairs × 5 years × 12 months × 2
   sides × ~22 trading days = ~7,920 day-level downloads, estimated at
   10-40 hours depending on network stability.
