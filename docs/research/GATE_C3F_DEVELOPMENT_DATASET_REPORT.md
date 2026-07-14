# Gate C.3F — Development Dataset Report

## Status: INCOMPLETE

The full development dataset (2015-01-01 through 2019-12-31) has not been
acquired. The infrastructure for durable, resumable acquisition is complete
and tested.

## Infrastructure Delivered

### Scope-Aware Certification
- `PARTITION_STRUCTURALLY_VALIDATED` — single month passes structural gate
- `PARTITION_EXPLORATORY_ONLY` — no data on either side
- `PARTITION_REJECTED` — failed structural checks
- `DATASET_CERTIFIED_FOR_DEVELOPMENT` — all 5 years pass pair-year gates
- `HOLDOUT_QUALITY_INSPECTED_ONLY` — structural quality only

### Daily Checkpoint System
- Day-level atomic persistence
- Monthly compaction after all days terminal
- Manifest persistence with full partition records
- Memory-bounded: one day at a time

### Failure Classification
- 11 explicit categories with retry eligibility
- Weekend/holiday not counted as failures
- Retryable: transient network, rate limit, timeout
- Non-retryable: parser error, checksum failure, market closed

### Persistent Runner
- PID file, heartbeat, structured progress
- Graceful SIGINT/SIGTERM handling
- Resume from last completed partition
- Status query command

### Bounded Concurrency
- Default 2 workers, max 4
- Shared rate limiter
- File-based partition locks with stale-lock recovery
- Deterministic manifest ordering

## Acquisition Priority

1. 2019 (event-smoke dataset) — in progress
2. 2015-2018 (full development) — pending
3. 2020-2022 (validation) — deferred
4. 2023-2025 (holdout) — quality inspection only

## Known Risks

1. Dukascopy CDN instability causes ~20-40% transient failure rate
2. Full development acquisition estimated at 10-40 hours
3. GBPUSD showed higher failure rates in June 2023 testing
