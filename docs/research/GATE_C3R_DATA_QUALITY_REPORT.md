# Gate C.3R — Data Quality Report

## Structural Integrity

All three pairs pass structural validation:
- Monotonic timestamps (verified)
- No duplicate bars within joined datasets
- Valid OHLC (high ≥ max(open, close), low ≤ min(open, close))
- No negative or zero prices
- No ask below bid (0 negative-spread bars across all pairs)

## Spread Statistics

| Pair | Median | P90 | P95 | P99 | Max |
|------|--------|-----|-----|-----|-----|
| EURUSD | 0.3 pips | 0.4 pips | 0.6 pips | 3.0 pips | 7.1 pips |
| GBPUSD | 1.0 pips | 1.3 pips | 2.3 pips | 7.3 pips | 36.9 pips |
| USDJPY | 0.6 pips | 0.9 pips | 1.3 pips | 5.4 pips | 27.7 pips |

All spreads are within plausible bounds for M1 FX data.

## Coverage

| Pair | Expected session minutes | Joined M1 bars | Notes |
|------|------------------------|-----------------|-------|
| EURUSD | ~31,680 | 25,732 | Ask-side download gaps |
| GBPUSD | ~31,680 | 17,565 | Network failures on both sides |
| USDJPY | ~31,680 | 31,375 | Near-complete coverage |

## Gap Analysis

- EURUSD max gap: 4,141 min (~69 hours, weekend)
- GBPUSD max gap: 8,466 min (~141 hours, download gap + weekends)
- USDJPY max gap: 2,886 min (~48 hours, weekend)

Weekend gaps are expected. Non-weekend gaps in GBPUSD are from
network failures during acquisition, not data quality issues.

## Bid/Ask Invariant Validation

All pairs pass BidAskBarSeries.validate_invariants():
- No negative spread at open
- No negative spread at close
- No zero/negative bid close
- Valid bid OHLC relations
- Valid ask OHLC relations

## Certification

| Pair | Status |
|------|--------|
| EURUSD | CERTIFIED_PRIMARY_DEVELOPMENT_DATA |
| GBPUSD | CERTIFIED_EXPLORATORY_ONLY |
| USDJPY | CERTIFIED_PRIMARY_DEVELOPMENT_DATA |

GBPUSD is exploratory due to incomplete coverage from network failures.
Re-acquisition with more retries would likely achieve full certification.
