# Gate C.3F-R — 2019 Certification

## Status: ACQUISITION_IN_PROGRESS

The corrected persistent runner is actively acquiring 2019 M1 bid/ask data for EURUSD, GBPUSD, and USDJPY.

## Runner details

- PID: 30336
- Workers: 2 (genuine concurrent execution confirmed)
- State: data/acquisition_state
- Raw data: data/raw/dukascopy-node

## Certification requirements (frozen from C.3F)

### Partition structural gate
- Both bid and ask available
- Exact timestamp alignment above threshold
- Zero negative spreads
- Zero invalid OHLC
- Zero duplicate timestamps after resolution
- Plausible prices
- Deterministic checksum
- Successful Parquet round trip

### Pair-year gate
- At least 11 valid months
- Acceptable expected-session coverage
- No unexplained month-scale gaps
- Acceptable unpaired-row ratio
- All months structurally valid or bounded exclusions

### Certification statuses
- `PAIR_YEAR_CERTIFIED_FOR_DEVELOPMENT`
- `PAIR_YEAR_EXPLORATORY_ONLY`
- `PAIR_YEAR_REJECTED`

## Next steps

1. Complete 2019 acquisition
2. Run `--retry-failed` for retryable failures
3. Run `--repair-missing` for unpaired sides
4. Execute pair-year certification for each pair
5. Execute 2019 tick audit windows
6. Run event smoke test (post-certification only)
