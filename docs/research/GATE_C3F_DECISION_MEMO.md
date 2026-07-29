# Gate C.3F — Decision Memo

## Decision: `PARTIAL_DEVELOPMENT_DATA_NOT_CERTIFIED`

## Summary

Gate C.3F delivered all required acquisition infrastructure improvements
but could not complete the full development dataset acquisition within
a single session. The acquisition system is now genuinely durable,
auditable, and efficient. The 2019 acquisition has been started using
the new daily checkpoint system.

## Achievements

### Certification Semantics (COMPLETE)
- Scope-aware vocabulary: partition, pair-year, dataset
- Holdout cannot be labeled development data (regression-tested)
- Single month cannot certify multi-year dataset (regression-tested)
- Missing years block development certification (regression-tested)
- 14 regression tests proving correct semantics

### Daily Checkpoints (COMPLETE)
- Day-level atomic persistence
- Monthly compaction after all days terminal
- Manifest persistence roundtrip
- Recovery from interrupted acquisition
- 12 tests covering checkpoints, compaction, and recovery

### Failure Categories (COMPLETE)
- 11 explicit categories with retry eligibility classification
- Weekend/holiday not treated as failures
- All categories tested for correct classification

### GBPUSD June 2023 Diagnosis (COMPLETE)
- Root cause: independent bid/ask download failures at day level
- 10 affected days identified with exact row counts
- Repair method documented (targeted day+side re-download)
- Not a timestamp mismatch, filtering, or parsing issue

### Acquisition Infrastructure (COMPLETE)
- Persistent runner with PID, heartbeat, graceful termination
- Bounded concurrency with shared rate limiter and partition locks
- Acquisition status CLI for observability
- Targeted repair mode (`--repair-missing`)
- Full partition records in manifests

### Tests (COMPLETE)
- 45 new Gate C.3F tests
- 615 total tests passing
- Zero Ruff errors in modified files

## Not Completed

1. **Full 2019 acquisition** — started but not complete
2. **2019 tick audit execution** — pending 2019 completion
3. **2019 event smoke test** — pending 2019 certification
4. **2015-2018 acquisition** — pending 2019 completion
5. **Full development dataset certification** — pending all years
6. **GBPUSD June 2023 repair execution** — infrastructure built,
   actual re-download not executed
7. **Worker concurrency benchmark** — deferred as network-bound

## How to Complete

```bash
# Start the persistent acquisition for 2019
python scripts/run_persistent_acquisition.py \
  --pairs EURUSD GBPUSD USDJPY \
  --start 2019-01-01 --end 2019-12-31 \
  --workers 2 --resume \
  --log-dir logs/acquisition --state-dir data/acquisition_state

# Check status
python scripts/run_persistent_acquisition.py \
  --status --state-dir data/acquisition_state

# After 2019 completes, acquire 2015-2018
python scripts/run_persistent_acquisition.py \
  --pairs EURUSD GBPUSD USDJPY \
  --start 2015-01-01 --end 2018-12-31 \
  --workers 2 --resume \
  --log-dir logs/acquisition --state-dir data/acquisition_state

# Repair GBPUSD June 2023
python scripts/acquire_dukascopy_node_history.py \
  --repair-missing --pair GBPUSD --year 2023 --month 06
```

## Risks

1. Dukascopy CDN instability (~20-40% transient failure rate per request)
2. Full development acquisition requires 10-40 hours of runtime
3. Rate-limiting risk increases with concurrent workers
4. No secondary provider overlap validation yet

## Holdout Integrity

- No detector, event funnel, or strategy code has touched 2023-2025 data
- Holdout access control (`guard_holdout`) technically enforced
- Persistent runner does not import strategy/event modules (tested)
- All holdout partitions labeled `HOLDOUT_QUALITY_INSPECTED_ONLY`

## Environment

- Node.js: v20.9.0
- dukascopy-node: 1.46.4
- Python: 3.13.5
- Branch: research/rigorous-intraday-smc-validation
