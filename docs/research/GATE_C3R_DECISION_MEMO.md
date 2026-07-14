# Gate C.3R — Decision Memo

## Decision

**PARTIAL_DATA_ACQUIRED_NOT_CERTIFIED**

## Summary

Gate C.3R successfully unblocked the data access bottleneck from Gate C.3
by integrating `dukascopy-node` as a pinned Node.js acquisition tool.
The complete acquisition, validation, and certification pipeline was
built and validated end-to-end on a representative month (2023-06).

The full 2015–2025 acquisition was not completed due to network download
latency (approximately 2-4 minutes per daily download with retries,
requiring an estimated 100+ hours for the full dataset).

## Achievements

### Infrastructure Built
1. **Pinned Node tool** (`tools/dukascopy-node/`): dukascopy-node 1.46.4,
   locked, tested, 0 npm vulnerabilities
2. **Python bridge** (`dukascopy_node_provider.py`): daily download with
   retry, monthly aggregation, bid/ask alignment, Parquet conversion
3. **Acquisition CLI** (`acquire_dukascopy_node_history.py`): dry-run,
   resumable, manifest generation
4. **Market calendar** (`market_calendar.py`): weekend/holiday gap
   classification, session coverage metrics
5. **Validation pipeline** (`validate_and_certify.py`): multi-month
   structural checks, spread statistics, invariant validation, resampling
6. **Holdout access control** (`holdout_access.py`): technical enforcement
   of split boundaries with purpose-based access checks
7. **Tick audit framework** (`tick_audit.py`): deterministic audit window
   selection, stratified across years/quarters/sessions

### Data Acquired and Validated
- 3 pairs × 1 month × 2 sides = 6 partitions
- 168,734 total M1 bars downloaded
- 0 negative-spread bars across all pairs
- All bid/ask OHLC invariants pass
- Successful resampling to M5, M15, H1, H4

### Certification Results (2023-06 only)
| Pair   | Certification                      | Joined Rows | Session Coverage |
|--------|------------------------------------|-------------|-----------------|
| EURUSD | CERTIFIED_PRIMARY_DEVELOPMENT_DATA | 25,732      | 81.5%           |
| GBPUSD | CERTIFIED_EXPLORATORY_ONLY         | 17,565      | 63.9%           |
| USDJPY | CERTIFIED_PRIMARY_DEVELOPMENT_DATA | 31,375      | 99.4%           |

### Spread Statistics
| Pair   | Median Spread | P99 Spread | Max Spread |
|--------|--------------|-----------|------------|
| EURUSD | 0.3 pips     | 3.0 pips  | 7.1 pips   |
| GBPUSD | 1.0 pips     | 7.3 pips  | 36.9 pips  |
| USDJPY | 0.6 pips     | 5.4 pips  | 27.7 pips  |

### Test Coverage
- 570 total tests, all passing (49 new for Gate C.3R)
- Node tool detection, output parsing, error propagation
- Bid/ask alignment, missing-side rejection
- Partition resumability, checksum stability
- Parquet roundtrip, resampling consistency
- Holdout access rejection (8 tests)
- Market calendar gap classification (5 tests)
- Tick audit framework (3 tests)
- Atomic completion (2 tests)
- Retryable vs non-retryable failures (3 tests)

### Holdout Protection
- `holdout_access.py` enforces purpose-based access control
- Data quality inspection of holdout period is PERMITTED
- Alpha research, event detection, campaigns on holdout are PROHIBITED
- `guard_holdout()` raises `ValueError` for unauthorized access
- No strategy, event, or alpha code has accessed holdout-period data

## What Remains

1. **Full acquisition**: 2015-01-01 to 2025-12-31 (792 partitions,
   estimated 100+ hours at current download speeds)
2. **Tick audit**: Plan generated (44 windows, seed=42), requires full
   dataset for execution
3. **Event smoke test**: Requires certified development-period data
   (currently only holdout-period data available)
4. **GBPUSD re-acquisition**: With more retries to achieve full certification
5. **Secondary provider**: OANDA/MT5 overlap validation (credentials not
   available; documented as future requirement)
6. **Native Python provider comparison**: Deferred to when both BI5 and
   dukascopy-node produce overlapping M1 data

## Unresolved Risks

1. **Network reliability**: Dukascopy CDN shows intermittent `fetch failed`
   errors; mitigated by day-level retries but not eliminated
2. **Download speed**: ~2-4 minutes per day with retries; parallelization
   would help but risks rate limiting
3. **Full acquisition time**: ~100+ hours for complete dataset; needs
   dedicated batch process or background runner
4. **No secondary source**: OANDA credentials not available; MT5 export
   not attempted; secondary validation is required for publication-grade claims
5. **GBPUSD bid/ask alignment**: 36% session missing rate needs re-acquisition

## Environment

- Starting SHA: `25f5102`
- Ending SHA: to be set at final commit
- Node.js: v20.9.0
- npm: 10.1.0
- dukascopy-node: 1.46.4
- Python: 3.13.5
- Tests: 570 total (49 new), all passing
- Ruff: 0 errors
- npm audit: 0 vulnerabilities
- npm test: 2/2 pass
