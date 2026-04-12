# Simplified Candidate Data Source Comparison

Generated: 2026-04-12T17:55:06.429594

## Data Quality

**EURUSD Yahoo**: 12,354 bars | Missing: 29.5% | Quality: 0.656
**GBPUSD Yahoo**: 12,356 bars | Missing: 29.5% | Quality: 0.666
**USDJPY Yahoo**: 12,268 bars | Missing: 30.0% | Quality: 0.679
**EURUSD Synth**: 12,529 bars | Missing: 28.5% | Quality: 0.700 | Spread: 0.000140
**GBPUSD Synth**: 12,529 bars | Missing: 28.5% | Quality: 0.700 | Spread: 0.000175
**USDJPY Synth**: 12,529 bars | Missing: 28.5% | Quality: 0.700 | Spread: 0.017536

## bos_only_usdjpy

| Source               | Trades |  Sharpe |     PF |   MaxDD |  Win% |            PnL |
|----------------------|--------|---------|--------|---------|-------|----------------|
| Yahoo Holdout        |    220 |   0.850 |   1.96 |   12.6% | 29.1% |      38,678.47 |
| Synth Train          |      0 |   0.000 |   0.00 |    0.0% |  0.0% |           0.00 |
| Synth Holdout        |      0 |   0.000 |   0.00 |    0.0% |  0.0% |           0.00 |

## bos_only_all_pairs

| Source               | Trades |  Sharpe |     PF |   MaxDD |  Win% |            PnL |
|----------------------|--------|---------|--------|---------|-------|----------------|
| Yahoo Holdout        |    253 |   0.154 |   1.11 |   12.7% | 31.2% |       4,215.01 |
| Synth Train          |      0 |   0.000 |   0.00 |    0.0% |  0.0% |           0.00 |
| Synth Holdout        |      0 |   0.000 |   0.00 |    0.0% |  0.0% |           0.00 |

## Cost Sensitivity (bos_only_usdjpy Yahoo Holdout)

|   Mult |   Sharpe |     PF |            PnL |   Win% |
|--------|----------|--------|----------------|--------|
|   0.25 |    0.919 |   2.09 |      41,775.92 | 49.1% |
|   0.50 |    0.896 |   2.05 |      40,743.43 | 44.5% |
|   0.75 |    0.873 |   2.00 |      39,710.95 | 43.2% |
|   1.00 |    0.850 |   1.96 |      38,678.47 | 29.1% |
|   1.50 |    0.805 |   1.88 |      36,613.50 | 26.8% |
|   2.00 |    0.760 |   1.80 |      34,548.54 | 25.5% |
|   3.00 |    0.669 |   1.66 |      30,418.60 | 24.1% |

## Source Robustness Summary

The synthetic data comparison isolates data-quality effects from strategy alpha.
