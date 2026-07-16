# Gate C.3F-R — 2019 Certification

## Status: ALL_THREE_PAIRS_CERTIFIED_FOR_DEVELOPMENT

All 72 partitions (3 pairs × 12 months × bid/ask) acquired successfully with
zero remaining failures. Each pair-year passes the frozen certification protocol.

## Acquisition summary

- Runner: persistent runner with 2 genuine concurrent workers
- Per-worker temp/cache isolation (fixed NODE_PROCESS_ERROR crash)
- Retry backoff: 5-15s exponential (fixed rapid-spawn crash)
- Total acquisition time: ~20 hours across multiple sessions
- Total rows: 2,113,534
- Total failures after retry: 0

## Pair-year certification results

### EURUSD 2019 — PAIR_YEAR_CERTIFIED_FOR_DEVELOPMENT

| Metric | Value |
|--------|-------|
| Bid rows | 334,565 |
| Ask rows | 329,052 |
| Joined rows | 316,276 |
| Bid-only | 18,289 |
| Ask-only | 12,776 |
| Negative spreads | 0 |
| Valid months | 12/12 |
| Session missing | 15.5% |
| Spread median | 0.000030 |
| Spread P95 | 0.000060 |
| Spread max | 0.001610 |

### GBPUSD 2019 — PAIR_YEAR_CERTIFIED_FOR_DEVELOPMENT

| Metric | Value |
|--------|-------|
| Bid rows | 354,231 |
| Ask rows | 361,899 |
| Joined rows | 343,011 |
| Bid-only | 11,220 |
| Ask-only | 18,888 |
| Negative spreads | 0 |
| Valid months | 12/12 |
| Session missing | 8.4% |
| Spread median | 0.000100 |
| Spread P95 | 0.000210 |
| Spread max | 0.004000 |

### USDJPY 2019 — PAIR_YEAR_CERTIFIED_FOR_DEVELOPMENT

| Metric | Value |
|--------|-------|
| Bid rows | 365,045 |
| Ask rows | 368,742 |
| Joined rows | 360,906 |
| Bid-only | 4,139 |
| Ask-only | 7,836 |
| Negative spreads | 0 |
| Valid months | 12/12 |
| Session missing | 3.6% |
| Spread median | 0.003000 |
| Spread P95 | 0.006000 |
| Spread max | 0.344000 |

## Threshold justification

Session missing and unpaired ratio thresholds account for dukascopy-node's
`flats=false` configuration, which independently filters flat-price bars from
each side. This is expected behavior, not a data quality issue:

- `MAX_SESSION_MISSING_PCT = 20.0%` — flat filtering + weekend partial data
- `MAX_UNPAIRED_RATIO = 0.15` — independent flat filtering per price side
- `MAX_NEGATIVE_SPREAD_RATIO = 0.001` — strict zero-tolerance in practice

## Canonical Parquet output

M1 bid/ask Parquet partitions written to `data/canonical/dukascopy/` for all
three pairs, all 12 months of 2019.

## Next steps

1. Execute 2019 tick audit windows (from frozen deterministic plan)
2. Run 2019 event smoke test (post-certification)
3. Begin 2015-2018 acquisition for full development dataset
