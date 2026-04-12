# Updated Candidate Comparison

Generated: 2026-04-12T13:34:19.674320

## Walk-Forward OOS Summary

| Metric                    |     sweep_plus_bos |  bos_continuation_only |
|---------------------------|--------------------|------------------------|
| OOS folds                 |                 10 |                     10 |
| Mean OOS Sharpe           |              0.194 |                  0.195 |
| Std OOS Sharpe            |              1.383 |                  1.383 |
| Min OOS Sharpe            |             -1.131 |                 -1.131 |
| Max OOS Sharpe            |              2.713 |                  2.713 |
| % folds Sharpe > 0        |                40% |                    40% |
| % folds Sharpe > 0.3      |                40% |                    40% |
| Mean OOS PF               |               1.36 |                   1.36 |
| Mean OOS MaxDD            |              13.0% |                  13.1% |
| Mean OOS Trades           |                182 |                    176 |

## Temporal Degradation Pattern

Checking whether OOS performance degrades systematically in later folds:

**sweep_plus_bos** (anchored):
- Early folds mean Sharpe: 0.232
- Late folds mean Sharpe: 0.310
- OK: Performance relatively stable across folds

**bos_continuation_only** (anchored):
- Early folds mean Sharpe: 0.233
- Late folds mean Sharpe: 0.310
- OK: Performance relatively stable across folds


## Champion Determination

Performance is **materially similar** between candidates under walk-forward.

Given similar performance, **bos_continuation_only** is preferred for simplicity 
(1 family vs 2 families).

**Updated champion: bos_continuation_only** (reason: similar_performance_prefer_simplicity)
