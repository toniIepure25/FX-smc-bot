# Strategy Simplification Report

**Full strategy Sharpe**: 1.804 (839 trades)
**Simplification score**: 0.75 (0=no action, 1=simplify aggressively)
**Complexity penalty**: 0.0000 Sharpe per extra family

**Recommendation**: STRONGLY RECOMMENDED: 4 of 6 families should be removed. Consider a simpler variant as champion.

## Component Analysis

| Family | Solo Sharpe | Solo Trades | Fragility | Verdict | Reasons |
|--------|------------|-------------|-----------|---------|---------|
| bos_continuation_only | 1.781 | 849 | 0.04 | keep | Strong standalone (1.781 vs full 1.804) |
| session_breakout_baseline | 0.220 | 49 | 0.59 | investigate | High solo fragility (0.59) |
| momentum_baseline | -0.106 | 54 | 1.00 | remove | Negative solo Sharpe (-0.106) |
| mean_reversion_baseline | -0.548 | 120 | 1.00 | remove | Negative solo Sharpe (-0.548) |
| fvg_retrace_only | -0.059 | 79 | 1.00 | remove | Negative solo Sharpe (-0.059) |
| sweep_reversal_only | 0.000 | 0 | 1.00 | remove | Too few solo trades (0) |
