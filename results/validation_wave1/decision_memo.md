# Research Decision Memo

**Date**: 2026-04-11T00:09:46.053211
**Decision**: REJECT
**Champion**: (none)
**Confidence**: high

## Executive Summary

- No candidate passed the deployment gate.

## What Works

- No candidates passed the deployment gate.

## What Is Fragile

- **session_breakout_baseline**: fragility=0.59, stressed Sharpe=0.089
- **momentum_baseline**: fragility=1.00, stressed Sharpe=-0.098
- **mean_reversion_baseline**: fragility=1.00, stressed Sharpe=-0.555
- **full_smc**: fragility=1.00, stressed Sharpe=-0.252
- **sweep_plus_fvg**: fragility=1.00, stressed Sharpe=-0.252
- **bos_plus_fvg**: fragility=1.00, stressed Sharpe=-0.252
- **fvg_retrace_only**: fragility=1.00, stressed Sharpe=-0.252
- **sweep_plus_bos**: fragility=1.00, stressed Sharpe=0.000
- **sweep_reversal_only**: fragility=1.00, stressed Sharpe=0.000
- **bos_continuation_only**: fragility=1.00, stressed Sharpe=0.000

## Simplification Recommendations

- session_breakout_baseline: simplicity=1.00, composite=0.502
- momentum_baseline: simplicity=1.00, composite=0.216
- mean_reversion_baseline: simplicity=1.00, composite=0.215

## Blocking Issues

- No viable champion identified.

## Next Steps

1. Review gate thresholds or improve strategy components.