# Gate C.3R — Tick Audit

## Status

**PLAN_GENERATED_PENDING_FULL_ACQUISITION**

## Audit Plan

The tick audit framework generates deterministic audit windows using
a fixed seed (42), stratified across all years (2015-2025), all four
quarters, and both London and New York sessions.

### Parameters
- **Seed**: 42
- **Total windows**: 44 (4 per year × 11 years)
- **Window duration**: 1 trading week (Monday-Saturday)
- **Session coverage**: ~50% London, ~50% New York
- **Plan hash**: `bbcebd0b6cc0`

### Tolerances (set before examining results)
- **Max OHLC diff**: 0.0 (tick-derived M1 must match downloaded M1 exactly)
- **Rationale**: Both tick and M1 data come from the same Dukascopy source;
  any difference indicates a parsing or aggregation error

### Implementation

File: `src/fx_smc_bot/data/tick_audit.py`

The plan is deterministic — running `generate_audit_plan(2015, 2025, seed=42)`
always produces the same 44 windows with the same plan hash.

## Deferred Reason

The tick audit requires:
1. Full M1 dataset for all pairs across the audit window dates
2. Tick data downloads for each audit window
3. Independent tick-to-M1 aggregation
4. Comparison with downloaded M1

Currently only 2023-06 M1 data is fully acquired. The full 2015-2025
acquisition is in progress and estimated at 100+ hours.

## Verification Protocol

When tick data becomes available:
1. For each audit window, download tick bid and ask data
2. Aggregate ticks to M1 independently for bid and ask:
   - open = first tick price
   - high = max tick price
   - low = min tick price
   - close = last tick price
3. Compare with downloaded M1 bid and M1 ask
4. Report OHLC differences, spread differences, volume differences
5. Fail if any difference exceeds the pre-set tolerance (0.0)
