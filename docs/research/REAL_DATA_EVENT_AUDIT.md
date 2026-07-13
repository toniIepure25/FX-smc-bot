# Real-Data Event Audit

**Date**: 2026-07-13
**Branch**: `research/rigorous-intraday-smc-validation`

---

## Status: BLOCKED_BY_DATA_OR_IMPLEMENTATION

This audit cannot be performed for two reasons:

### 1. No M5 Real Data Available
The intraday SMC strategies require M5 execution-timeframe data. Only M15 (3 months, Yahoo Finance) and H1/H4 (2 years, Yahoo Finance) are available. The M15 data is too coarse for the fine-grained event tracing required.

### 2. V2 Detectors Not Integrated
The intraday strategy detectors (`SweepReversalDetectorV2`, `AcceptanceContinuationDetector`, `OpeningRangeDetector`) are not wired into the `BacktestEngine` campaign pipeline. Event traces cannot be generated from a campaign run.

---

## What This Audit Would Contain (When Unblocked)

For a deterministic sample of 20+ events per strategy:
- All input candles used
- Liquidity-level creation and availability time
- Breach / reclaim / acceptance time
- MSS swing and confirmation time
- Displacement metrics (body ratio, TR ratio, CLV)
- FVG creation and activation time
- Order-submission and earliest fill time
- Actual fill time
- Stop loss and take profit levels
- Invalidation reason (if applicable)
- Exit reason and exit time

### Causality Assertion
Every event must use only information available at its timestamp. This is verified at the unit-test level for each detector, but full-pipeline event traces require the integration described above.

---

## Required Actions

1. Integrate V2 detectors into campaign engine
2. Acquire M5 bid/ask data
3. Define development-only date boundary
4. Run detectors on development data
5. Sample 20+ events per strategy using fixed seed
6. Export machine-readable event traces
7. Manually verify causality assertions
