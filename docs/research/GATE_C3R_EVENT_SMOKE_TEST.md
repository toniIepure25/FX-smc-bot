# Gate C.3R — Event Smoke Test

## Status

DEFERRED — requires certified multi-year development data.

## Rationale

The event smoke test runs V2 detectors on certified development-period
data (2015–2019). Current acquisition covers only 2023-06, which falls
in the holdout period. Running detectors on holdout data is prohibited.

## Planned Test

Once full development data is certified:

1. Select interval: 2018-01-01 to 2018-06-30
2. Run all three V2 detectors
3. Report event funnels only (no PnL)
4. Diagnose any zero-funnel stages

## Expected Funnels

### Sweep Reversal
liquidity levels → breaches → reclaims → MSS → displacement → FVG →
intents → orders → fills → expiries → closes

### Acceptance Continuation
levels → breaks → acceptance → displacement → FVG → retests →
intents → fills → invalidations

### Opening Range
completed ranges → breakouts → displacement → FVG → retests →
intents → fills → expiries
