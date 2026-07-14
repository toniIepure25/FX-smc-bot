# Gate C.3R — Tick Audit

## Status

DEFERRED — requires full 2015–2025 acquisition to generate stratified
audit windows.

## Preregistered Tolerances

Set before examining any results:

- OHLC difference tolerance: ≤ 0.1 pips
- Spread difference tolerance: ≤ 0.5 pips
- Volume difference tolerance: ≤ 5%

## Planned Audit Window Selection

- Random seed: 42
- Stratification: by year, quarter, session (London/New York)
- Minimum: 12 complete trading weeks across the dataset
- Selection criterion: deterministic, independent of price content

## Method

1. Download tick data for preregistered windows
2. Aggregate tick bid/ask to M1 independently
3. Compare with downloaded M1 bid and M1 ask
4. Report OHLC/spread/volume differences

## Current Observation

For the representative month (2023-06), dukascopy-node M1 data shows:
- Consistent 1-minute gaps (median gap = 1.0 min)
- Valid OHLC relations on both bid and ask
- Plausible spread distributions

Full tick audit will be completed during extended acquisition phase.
