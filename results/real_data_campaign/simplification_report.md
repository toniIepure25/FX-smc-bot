# Strategy Simplification Report

**Full strategy Sharpe**: 1.529 (1095 trades)
**Simplification score**: 0.50 (0=no action, 1=simplify aggressively)
**Complexity penalty**: 0.0000 Sharpe per extra family

**Recommendation**: RECOMMENDED: Some families underperform. Investigate 2 families and consider removing 2.

## Component Analysis

| Family | Solo Sharpe | Solo Trades | Fragility | Verdict | Reasons |
|--------|------------|-------------|-----------|---------|---------|
| sweep_reversal_only | 1.528 | 707 | 0.00 | keep | Strong standalone (1.528 vs full 1.529) |
| bos_continuation_only | 1.481 | 1131 | 0.00 | keep | Strong standalone (1.481 vs full 1.529) |
| session_breakout_baseline | 0.057 | 226 | 0.97 | investigate | High solo fragility (0.97) |
| momentum_baseline | 0.022 | 71 | 1.00 | investigate | High solo fragility (1.00) |
| fvg_retrace_only | -0.184 | 123 | 1.00 | remove | Negative solo Sharpe (-0.184) |
| mean_reversion_baseline | -0.111 | 187 | 1.00 | remove | Negative solo Sharpe (-0.111) |
