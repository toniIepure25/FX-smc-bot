# Updated Deployment Readiness Report

Generated: 2026-04-12T13:34:19.676612

## Champion: bos_continuation_only
Risk profile: size_030_cb125
Champion reason: similar_performance_prefer_simplicity

## Training Performance

| Period                    | Trades |  Sharpe |     PF |   MaxDD |  Win% |          PnL |  Calmar |
|---------------------------|--------|---------|--------|---------|-------|--------------|---------|
| Train                     |    513 |   2.076 |   5.58 |   13.4% | 56.3% | 8,553,133.38 |  365.67 |
| Holdout                   |    253 |   0.154 |   1.11 |   12.7% | 31.2% |     4,215.01 |    0.57 |

## Walk-Forward OOS Performance

- Mean OOS Sharpe: 0.195
- % folds with positive Sharpe: 40%
- % folds with Sharpe > 0.3: 40%
- Mean OOS MaxDD: 13.1%

## Execution Stress

- Stress test passed: Yes

## Regime Mitigation

- Useful mitigations found: 0

## Deployment Gate Status

- Holdout gate verdict: fail
- Blocking failures: sharpe_ratio, win_rate
- WF-average gate verdict: fail
- WF blocking failures: sharpe_ratio

## Unresolved Risks

1. Holdout Sharpe below deployment threshold (0.3)
2. Yahoo Finance data lacks bid/ask spreads
3. Fixed spread assumption may not reflect real execution
4. Walk-forward suggests potential structural weakness

## Recommendation: **HOLD_FOR_MORE_VALIDATION** (confidence: low-medium)