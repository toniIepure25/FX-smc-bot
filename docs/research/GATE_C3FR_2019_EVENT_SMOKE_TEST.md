# Gate C.3F-R — 2019 Event Smoke Test

## Status: DEFERRED_PENDING_2019_CERTIFICATION

Event funnels are permitted only after 2019 data passes pair-year certification.

## Constraints

- No PnL calculation
- No strategy performance metrics
- No parameter tuning
- No holdout data access
- Use frozen canonical V2 configurations

## Funnels to report

### Sweep Reversal
levels → breaches → reclaims → MSS → displacement → FVG → intents → fills → expiries → closed

### Acceptance Continuation
levels → breaks → acceptance → displacement → FVG → retests → intents → fills → invalidations

### Opening Range (London + New York)
ranges → breakouts → displacement → FVG → retests → intents → fills → expiries

## Breakdown dimensions
- Pair (EURUSD, GBPUSD, USDJPY)
- Month
- Direction (long/short)
- Session (London/New York)
- Liquidity-level type
