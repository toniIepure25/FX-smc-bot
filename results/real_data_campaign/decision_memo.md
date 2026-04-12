# Research Decision Memo

**Date**: 2026-04-11T20:54:36.284334
**Decision**: REJECT
**Champion**: (none)
**Confidence**: high

## Executive Summary

- No candidate passed the deployment gate.

## What Works

- No candidates passed the deployment gate.

## What Is Fragile

- **session_breakout_baseline**: fragility=0.97, stressed Sharpe=0.001
- **momentum_baseline**: fragility=1.00, stressed Sharpe=-0.012
- **fvg_retrace_only**: fragility=1.00, stressed Sharpe=-0.224
- **mean_reversion_baseline**: fragility=1.00, stressed Sharpe=-0.136

## Simplification Recommendations

- sweep_plus_bos: simplicity=1.00, composite=0.632
- full_smc: simplicity=1.00, composite=0.625
- sweep_plus_fvg: simplicity=1.00, composite=0.614

## Blocking Issues

- No viable champion identified.

## Next Steps

1. Review gate thresholds or improve strategy components.