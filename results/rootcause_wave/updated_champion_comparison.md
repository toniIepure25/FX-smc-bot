# Updated Champion Comparison

Generated: 2026-04-12T15:14:32.188577

## 1. Holdout Performance Summary

| Variant                          | Pairs                | Trades |  Sharpe |     PF |   MaxDD |  Win% |            PnL |
|----------------------------------|----------------------|--------|---------|--------|---------|-------|----------------|
| sweep_plus_bos | All 3 pairs     | All 3 pairs          |    253 |   0.154 |   1.11 |   12.7% | 31.2% |       4,215.01 |
| bos_continuation_only | All 3 pairs | All 3 pairs          |    253 |   0.154 |   1.11 |   12.7% | 31.2% |       4,215.01 |
| sweep_reversal_only | All 3 pairs | All 3 pairs          |    155 |  -0.379 |   0.70 |   13.0% | 32.3% |      -8,534.93 |

## 2. Walk-Forward OOS Comparison

| Candidate                    | Mean Sharpe |    Std | Positive |  >0.3 |
|------------------------------|-------------|--------|----------|-------|
| sweep_plus_bos               |       0.279 |  1.365 | 2/5      | 2/5   |
| bos_continuation_only        |       0.279 |  1.365 | 2/5      | 2/5   |

## 3. Comprehensive Scoring

| Metric                       |     sweep_plus_bos |  bos_continuation_only |
|------------------------------|--------------------|------------------------|
| train_sharpe                 |              2.076 |                  1.948 |
| holdout_sharpe               |              0.154 |                  0.154 |
| wf_mean_sharpe               |              0.279 |                  0.279 |
| wf_pct_positive              |              40.0% |                  40.0% |
| holdout_dd                   |              12.7% |                  12.7% |
| holdout_trades               |                253 |                    253 |
| pair_diversification         |             100.0% |                 100.0% |
| simplicity                   |              50.0% |                 100.0% |
| composite                    |              0.372 |                  0.422 |

## 4. Champion Determination

**Updated Champion: bos_continuation_only** (reason: higher composite score (0.422 vs 0.372))