# Updated Deployment Readiness Report

Generated: 2026-04-12T15:14:32.189184

## Champion: bos_continuation_only
Risk profile: size_030_cb125
Champion selection reason: higher composite score (0.422 vs 0.372)

## Training vs Holdout

| Label                        | Trades |  Sharpe |     PF |   MaxDD |  Win% |            PnL |  Calmar |
|------------------------------|--------|---------|--------|---------|-------|----------------|---------|
| Train                        |    513 |   2.076 |   5.58 |   13.4% | 56.3% |   8,553,133.38 |  365.67 |
| Holdout                      |    253 |   0.154 |   1.11 |   12.7% | 31.2% |       4,215.01 |    0.57 |

## Walk-Forward OOS Performance (bos_continuation_only)

- Mean OOS Sharpe: 0.279
- % folds positive: 40%
- % folds above 0.3: 40%
- Fold Sharpes: ['-0.281', '0.747', '-0.652', '2.713', '-1.131']

## Root Causes of Holdout Weakness

- win-rate collapse (primary)
- winner size collapse
- extreme USDJPY concentration (100% of train PnL)
- sweep_reversal family reversal (profitable in train, loss-making in holdout)

## Data Quality Impact

- Synthetic holdout Sharpe: -0.743
- Yahoo holdout Sharpe: 0.154
- Data quality is NOT the primary issue

## Pair Concentration

- sweep_plus_bos: All-pairs Sharpe=0.154 vs USDJPY-only Sharpe=1.172
- bos_continuation_only: All-pairs Sharpe=0.154 vs USDJPY-only Sharpe=0.850

## Recommendation: **CONTINUE_WITH_SIMPLIFICATION** (confidence: low-medium)