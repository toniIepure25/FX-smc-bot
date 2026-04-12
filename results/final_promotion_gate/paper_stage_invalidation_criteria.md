# Paper Stage Invalidation Criteria

Generated: 2026-04-12T18:47:22.265509

## Hard Stops (Immediate Suspension)

1. Paper Sharpe < 0.0 after 4 complete weeks
2. Drawdown exceeds 15% at any point
3. Win rate < 15% over any 2-week rolling window
4. Zero signals for 5 consecutive trading days
5. Circuit breaker fires

## Review Triggers (Escalation Required)

1. Paper Sharpe < 0.3 after 6 weeks
2. Signal frequency deviates > 50% from backtest baseline
3. Win rate < 20% over any 3-week window
4. Drawdown exceeds 10%

## Expected Baselines

| Metric | Expected Range | Source |
|--------|---------------|--------|
| Weekly trades | 5-12 | Holdout (220 over ~11 weeks) |
| Win rate | 22-38% | Holdout (29.1%) |
| Sharpe (annualized) | 0.3-1.5 | OOS distribution (mean=1.599) |
| Max drawdown | < 15% | Holdout (12.6%) |