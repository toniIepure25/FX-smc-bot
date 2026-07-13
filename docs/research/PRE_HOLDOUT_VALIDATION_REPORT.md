# Pre-Holdout Validation Report

**Branch**: `research/rigorous-intraday-smc-validation`
**Date**: 2026-07-13

---

## Status: BLOCKED

This report cannot be completed because two blocking issues prevent any strategy evaluation:

1. **Implementation**: The V2 intraday SMC detectors are not integrated into the campaign/backtest engine
2. **Data**: No M5/M1 bid/ask real data is available

See `PRE_HOLDOUT_DECISION_MEMO.md` for complete details.

---

## Implementation Audit Results

Five critical defects were found and fixed during the independent audit:

| # | Defect | Severity | Status |
|---|--------|----------|--------|
| 1 | PSR/DSR/MTRL received annualized SR instead of daily | CRITICAL | Fixed |
| 2 | Commission not deducted from portfolio equity | HIGH | Fixed |
| 3 | Same-bar SL/TP exit not wired into engine | HIGH | Fixed |
| 4 | Prop simulation daily loss semantics wrong | HIGH | Fixed |
| 5 | Mypy type errors in campaign/prop modules | LOW | Fixed |

All 459 tests pass after fixes. All previous experimental outputs that used PSR, equity curves, or prop simulation are invalidated.

---

## Development Campaign Results

Not available — blocked.

## Validation Campaign Results

Not available — blocked.

## Preliminary Prop Simulation

Not available — blocked.

---

## Required Actions to Unblock

1. Integrate V2 intraday detectors into BacktestEngine or create dedicated intraday campaign engine
2. Acquire M5 bid/ask FX data (Dukascopy recommended) covering ≥2014-2024
3. Run complete data certification pipeline
4. Define and freeze date splits
5. Re-run this entire validation gate
