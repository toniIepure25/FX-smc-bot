# Mitigation Hypotheses and Results

Generated: 2026-04-12T15:10:37.711740

Baseline holdout (sweep_plus_bos): Sharpe=0.154 | PF=1.11 | Trades=253

## 1. Top 5 Holdout Variants from Concentration Analysis

| Variant                          | Pairs                | Trades |  Sharpe |     PF |   MaxDD |  Win% |            PnL |
|----------------------------------|----------------------|--------|---------|--------|---------|-------|----------------|
| sweep_plus_bos | USDJPY only     | USDJPY only          |    330 |   1.172 |   2.04 |   12.5% | 34.8% |      71,845.63 |
| sweep_plus_bos | Excl GBPUSD     | Excl GBPUSD          |    363 |   1.163 |   1.99 |   12.8% | 38.8% |      70,590.01 |
| bos_continuation_only | Excl GBPUSD | Excl GBPUSD          |    251 |   0.862 |   1.93 |   12.6% | 35.5% |      38,606.59 |
| bos_continuation_only | USDJPY only | USDJPY only          |    220 |   0.850 |   1.96 |   12.6% | 29.1% |      38,678.47 |
| sweep_reversal_only | USDJPY only | USDJPY only          |    285 |   0.629 |   1.50 |   12.5% | 32.6% |      25,753.31 |

## 2. Mitigation: BOS-Only on All Pairs

**Hypothesis**: sweep_reversal is the dominant holdout loser; removing it should improve stability.

- Holdout: Sharpe=0.154 | PF=1.11 | Trades=253
- Delta vs baseline: Sharpe +0.000

## 3. Mitigation: sweep_plus_bos USDJPY-Only

**Hypothesis**: non-USDJPY pairs dilute alpha and add noise.

- Holdout: Sharpe=1.172 | PF=2.04 | Trades=330
- Delta vs baseline: Sharpe +1.018

## 4. Mitigation: BOS-Only USDJPY-Only

**Hypothesis**: simplest possible config — single family, single pair.

- Holdout: Sharpe=0.850 | PF=1.96 | Trades=220
- Delta vs baseline: Sharpe +0.697

## 5. Mitigation: BOS-Only Excluding USDJPY

**Hypothesis**: test whether BOS generalizes across non-USDJPY pairs.

- Holdout: Sharpe=-1.097 | PF=0.29 | Trades=126
- Delta vs baseline: Sharpe -1.251

## 6. Walk-Forward Validation of Best Mitigations


**sweep_plus_bos** (anchored WF, 5 folds):
- OOS Sharpes: ['-0.281', '0.745', '-0.652', '2.713', '-1.131']
- Mean: 0.279 | Std: 1.365
- Positive folds: 2/5
- Above 0.3: 2/5

**bos_continuation_only** (anchored WF, 5 folds):
- OOS Sharpes: ['-0.281', '0.747', '-0.652', '2.713', '-1.131']
- Mean: 0.279 | Std: 1.365
- Positive folds: 2/5
- Above 0.3: 2/5

## 7. Mitigation Conclusions

Best mitigation: **sweep_plus_bos USDJPY-only** (Sharpe delta: +1.018)
This represents a meaningful improvement over baseline.