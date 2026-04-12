# Candidate Ranking

| Rank | Label | Composite | Sharpe | Stressed | Simplicity | OOS | Fragility | Gate | Recommendation |
|------|-------|-----------|--------|----------|------------|-----|-----------|------|----------------|
| 1 | sweep_plus_bos | 0.632 | 1.500 | 1.500 | 1.00 | 1.00 | 0.00 | fail | REJECT: fails deployment gate |
| 2 | full_smc | 0.625 | 1.529 | 1.517 | 1.00 | 1.00 | 0.01 | fail | REJECT: fails deployment gate |
| 3 | sweep_plus_fvg | 0.614 | 1.519 | 1.522 | 1.00 | 1.00 | 0.00 | fail | REJECT: fails deployment gate |
| 4 | bos_plus_fvg | 0.604 | 1.497 | 1.465 | 1.00 | 1.00 | 0.02 | fail | REJECT: fails deployment gate |
| 5 | sweep_reversal_only | 0.601 | 1.528 | 1.528 | 1.00 | 1.00 | 0.00 | fail | REJECT: fails deployment gate |
| 6 | bos_continuation_only | 0.598 | 1.481 | 1.474 | 1.00 | 1.00 | 0.00 | fail | REJECT: fails deployment gate |
| 7 | session_breakout_baseline | 0.422 | 0.057 | 0.001 | 1.00 | 1.00 | 0.97 | fail | REJECT: fails deployment gate |
| 8 | momentum_baseline | 0.417 | 0.022 | -0.012 | 1.00 | 1.00 | 1.00 | fail | REJECT: fails deployment gate |
| 9 | fvg_retrace_only | 0.216 | -0.184 | -0.224 | 1.00 | 0.00 | 1.00 | fail | REJECT: fails deployment gate |
| 10 | mean_reversion_baseline | 0.216 | -0.111 | -0.136 | 1.00 | 0.00 | 1.00 | fail | REJECT: fails deployment gate |