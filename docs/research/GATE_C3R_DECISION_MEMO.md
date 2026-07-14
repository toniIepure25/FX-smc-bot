# Gate C.3R — Decision Memo

## Decision

**PARTIAL_DATA_ACQUIRED_NOT_CERTIFIED**

## Summary

Gate C.3R successfully unblocked the data access bottleneck from Gate C.3
by integrating `dukascopy-node` as a pinned Node.js acquisition tool.
The complete acquisition, validation, and certification pipeline was
built and validated end-to-end on a representative month (2023-06).

However, the full 2015–2025 acquisition was not completed within the
available session time due to the volume of data (792 partitions) and
network latency (~2-4 minutes per daily download with retries).

## Achievements

### Infrastructure Built
1. **Pinned Node tool** (`tools/dukascopy-node/`): dukascopy-node 1.46.4,
   locked, tested, 0 npm vulnerabilities
2. **Python bridge** (`dukascopy_node_provider.py`): daily download with
   retry, monthly aggregation, bid/ask alignment, Parquet conversion
3. **Acquisition CLI** (`acquire_dukascopy_node_history.py`): dry-run,
   resumable, manifest generation
4. **Market calendar** (`market_calendar.py`): weekend/holiday classification
5. **Validation pipeline** (`validate_and_certify.py`): structural checks,
   spread statistics, invariant validation, resampling

### Data Acquired and Validated
- 3 pairs × 1 month × 2 sides = 6 partitions
- 168,734 total M1 bars downloaded
- 0 negative-spread bars
- All bid/ask OHLC invariants pass
- Successful resampling to M5, M15, H1, H4

### Certification Results (2023-06 only)
| Pair | Certification | Joined Rows |
|------|--------------|-------------|
| EURUSD | CERTIFIED_PRIMARY_DEVELOPMENT_DATA | 25,732 |
| GBPUSD | CERTIFIED_EXPLORATORY_ONLY | 17,565 |
| USDJPY | CERTIFIED_PRIMARY_DEVELOPMENT_DATA | 31,375 |

### Test Coverage
- 26 new tests for Gate C.3R
- Node tool detection, output parsing, error propagation
- Bid/ask alignment, missing-side rejection
- Partition resumability, checksum stability
- Parquet roundtrip, resampling consistency
- Holdout access rejection

## What Remains

1. **Full acquisition**: 2015-01-01 to 2025-12-31 (792 partitions,
   estimated 100+ hours at current download speeds)
2. **Tick audit**: Requires full dataset for stratified window selection
3. **Event smoke test**: Requires certified development-period data
4. **Secondary provider**: OANDA/MT5 overlap validation
5. **GBPUSD re-acquisition**: With more retries to achieve full certification

## Unresolved Risks

1. **Network reliability**: Dukascopy CDN shows intermittent `fetch failed`
   errors; mitigated by day-level retries but not eliminated
2. **Download speed**: ~2-4 minutes per day with retries; parallelization
   would help but risks rate limiting
3. **Full acquisition time**: ~100+ hours for complete dataset; needs
   dedicated batch process or background runner
4. **No secondary source**: OANDA credentials not available; MT5 export
   not attempted

## Environment

- Starting SHA: `25f5102`
- Node.js: v20.9.0
- npm: 10.1.0
- dukascopy-node: 1.46.4
- Python: 3.x
- Tests: 26 new (547 total), all passing
- Ruff: 0 errors
- npm audit: 0 vulnerabilities
