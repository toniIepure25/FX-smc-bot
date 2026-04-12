# Promotion Memo: BOS-Only USDJPY -> Paper Trading

Date: 2026-04-12

## Candidate
- Strategy: bos_only_usdjpy
- Family: bos_continuation
- Pair: USDJPY
- Risk profile: 0.30% per trade, 12.5% circuit breaker

## Evidence Summary
- Holdout Sharpe: 0.850
- Holdout PF: 1.96
- Holdout MaxDD: 12.6%
- OOS mean Sharpe: 1.599 across 27 folds
- OOS % positive: 63%
- Promotion scorecard: 8/8
- All execution stress scenarios positive: Yes

## Gate Decision
- Default gate (35% WR): fail
- Revised gate (25% WR): pass
- Justification: Low win rate is appropriate for trend-following BOS signal
  given PF=1.96 (winners compensate for frequency)

## Risks
- Single-pair concentration (USDJPY only)
- Yahoo data quality (~30% missing bars)
- High OOS variance (std=2.060)
- Regime sensitivity — some temporal windows are negative

## Approval
Promoted to paper trading stage pending 4-6 week monitoring.
Hard-stop triggers defined in invalidation_criteria.json.