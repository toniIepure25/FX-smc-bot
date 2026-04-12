# Strategy Simplification Report

**Full strategy Sharpe**: 1.804 (839 trades)
**Simplification score**: 0.25 (0=no action, 1=simplify aggressively)
**Complexity penalty**: 0.0118 Sharpe per extra family

**Recommendation**: MARGINAL: Added complexity provides little Sharpe improvement per family. The reduced variant may be a safer deployment candidate.

**Best reduced variant**: bos_continuation_only (Sharpe=1.781)

## Component Analysis

| Family | Solo Sharpe | Solo Trades | Fragility | Verdict | Reasons |
|--------|------------|-------------|-----------|---------|---------|
| bos_continuation_only | 1.781 | 849 | 0.04 | keep | Strong standalone (1.781 vs full 1.804) |
| session_breakout_baseline | 0.220 | 49 | 0.59 | investigate | High solo fragility (0.59) |
