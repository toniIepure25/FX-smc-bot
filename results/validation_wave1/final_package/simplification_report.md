# Strategy Simplification Report

**Full strategy Sharpe**: -0.087 (87 trades)
**Simplification score**: 0.92 (0=no action, 1=simplify aggressively)
**Complexity penalty**: 0.0000 Sharpe per extra family

**Recommendation**: STRONGLY RECOMMENDED: 5 of 6 families should be removed. Consider a simpler variant as champion.

## Component Analysis

| Family | Solo Sharpe | Solo Trades | Fragility | Verdict | Reasons |
|--------|------------|-------------|-----------|---------|---------|
| session_breakout_baseline | 0.220 | 49 | 0.59 | investigate | High solo fragility (0.59) |
| momentum_baseline | -0.106 | 54 | 1.00 | remove | Negative solo Sharpe (-0.106) |
| mean_reversion_baseline | -0.548 | 120 | 1.00 | remove | Negative solo Sharpe (-0.548) |
| fvg_retrace_only | -0.087 | 87 | 1.00 | remove | Negative solo Sharpe (-0.087) |
| sweep_reversal_only | 0.000 | 0 | 1.00 | remove | Too few solo trades (0) |
| bos_continuation_only | 0.000 | 0 | 1.00 | remove | Too few solo trades (0) |
