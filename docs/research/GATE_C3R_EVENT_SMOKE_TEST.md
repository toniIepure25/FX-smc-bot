# Gate C.3R — Event Smoke Test

## Status

**DEFERRED_PENDING_DEVELOPMENT_PERIOD_DATA**

## Reason

The event smoke test requires certified development-period data
(2015-2019). Currently, only holdout-period data (2023-06) has been
acquired. Running event detection or strategy code on holdout data
is prohibited per gate requirements.

Background acquisition of 2019-01 data (development period) is in
progress but has not yet completed.

## Plan

When development-period M1 bid/ask data is certified:

1. Load a limited development-only interval (e.g., 2019-01)
2. Run V2 detectors without calculating financial performance
3. Report event funnels only:

### Sweep Reversal Funnel
- Liquidity levels → Breaches → Reclaims → MSS → Displacement → FVG
- Intents → Orders → Fills → Expiries → Closes

### Acceptance Continuation Funnel
- Levels → Breaks → Acceptance → Displacement → FVG → Retests
- Intents → Fills → Invalidations

### Opening Range Funnel
- Completed ranges → Breakouts → Displacement → FVG → Retests
- Intents → Fills → Session expiries

## Requirements

- Must use certified, non-holdout data only
- Must not calculate Sharpe, profit factor, win rate, expectancy, or PnL
- Must not relax detector parameters
- If a funnel reaches zero events, diagnose the exact stage without
  changing parameters

## Holdout Protection

The `holdout_access.py` module ensures that event detection code
cannot access holdout-period timestamps. Attempting to load holdout
data for event detection raises `ValueError`.
