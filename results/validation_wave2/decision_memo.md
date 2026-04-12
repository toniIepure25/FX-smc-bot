# Research Decision Memo

**Date**: 2026-04-11T17:09:12.565186
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
- **sweep_plus_fvg**: fragility=1.00, stressed Sharpe=-0.259
- **fvg_retrace_only**: fragility=1.00, stressed Sharpe=-0.259
- **sweep_reversal_only**: fragility=1.00, stressed Sharpe=0.000

## Simplification Recommendations

- full_smc: simplicity=1.00, composite=0.604
- bos_plus_fvg: simplicity=1.00, composite=0.604
- sweep_plus_bos: simplicity=1.00, composite=0.602

## Blocking Issues

- No viable champion identified.

## Next Steps

1. Review gate thresholds or improve strategy components.