# Candidate Ranking

| Rank | Label | Composite | Sharpe | Stressed | Simplicity | OOS | Fragility | Gate | Recommendation |
|------|-------|-----------|--------|----------|------------|-----|-----------|------|----------------|
| 1 | full_smc | 0.604 | 1.804 | 1.726 | 1.00 | 1.00 | 0.04 | conditional | CONDITIONAL: marginal candidate, review before promoting |
| 2 | bos_continuation_only | 0.602 | 1.781 | 1.714 | 1.00 | 1.00 | 0.04 | conditional | CONDITIONAL: marginal candidate, review before promoting |
| 3 | session_breakout_baseline | 0.502 | 0.220 | 0.089 | 1.00 | 1.00 | 0.59 | fail | REJECT: fails deployment gate |