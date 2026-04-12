# Research Decision Memo

**Date**: 2026-04-11T17:52:53.295310
**Decision**: CONDITIONAL_PROMOTE
**Champion**: full_smc
**Confidence**: medium

## Executive Summary

- Champion passes blocking gates but has warnings.

## What Works

- **full_smc**: Sharpe=1.804, composite=0.604
- **bos_continuation_only**: Sharpe=1.781, composite=0.602

## What Is Fragile

- **session_breakout_baseline**: fragility=0.59, stressed Sharpe=0.089

## Simplification Recommendations

- full_smc: simplicity=1.00, composite=0.604
- bos_continuation_only: simplicity=1.00, composite=0.602
- session_breakout_baseline: simplicity=1.00, composite=0.502

## Next Steps

1. Review warnings and run paper trading with caution.