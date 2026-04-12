# Simplified Promotion Readiness

Generated: 2026-04-12T18:10:45.943441

## Primary Candidate: bos_only_usdjpy
- Family: bos_continuation
- Pairs: USDJPY
- Risk: standard

## Holdout Gate

- Verdict: fail
- Sharpe: 0.850 (threshold: 0.3)
- PF: 1.96 (threshold: 1.1)
- MaxDD: 12.6% (threshold: 20%)
- Trades: 220 (threshold: 30)
- Win%: 29.1% (threshold: 35%)
- Blocking failures: win_rate

## Walk-Forward Gate

- OOS mean Sharpe: 1.442
- % positive folds: 60%
- Stress test: PASSED
- WF gate verdict: fail
- WF blocking failures: profit_factor

## Promotion Decision: **CONDITIONAL_PROMOTE** (confidence: low-medium)

### Paper-Stage Checklist

- [ ] Deploy with frozen config (bos_continuation, USDJPY, size_030_cb125)
- [ ] Monitor for 4-6 weeks minimum
- [ ] Weekly Sharpe checkpoint vs holdout baseline
- [ ] Signal funnel comparison (live vs backtest)
- [ ] Drawdown alert if > 15%

### Invalidation Criteria

- Paper Sharpe < 0.0 after 4 weeks
- Win rate < 20% over any 2-week window
- Drawdown > 15%
- Signal frequency deviates > 50% from backtest

### Review Checkpoints

- Week 2: Initial signal funnel audit
- Week 4: First Sharpe assessment
- Week 6: Full promotion review