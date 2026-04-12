# BOS-Only USDJPY Data Validation

Generated: 2026-04-12T18:42:48.223459

## Yahoo vs Synthetic Comparison

| Label                            | Trades |  Sharpe |     PF |   MaxDD |  Win% |            PnL |  Calmar |
|----------------------------------|--------|---------|--------|---------|-------|----------------|---------|
| Yahoo Train                      |    429 |   1.930 |   5.88 |   12.8% | 58.7% |   5,705,609.62 |  255.96 |
| Yahoo Holdout                    |    220 |   0.850 |   1.96 |   12.6% | 29.1% |      38,678.47 |    5.26 |
| Synth Train                      |      0 |   0.000 |   0.00 |    0.0% |  0.0% |           0.00 |    0.00 |
| Synth Holdout                    |      0 |   0.000 |   0.00 |    0.0% |  0.0% |           0.00 |    0.00 |

## Data Quality

**USDJPY Yahoo**: 12,268 bars | Missing: 30.0% | Quality: 0.679
**USDJPY Synth**: 12,529 bars | Missing: 28.5% | Quality: 0.699 | Spread: 0.017569

## Key Findings

- Yahoo holdout Sharpe: 0.850 | Synth holdout Sharpe: 0.000
- Delta: +0.850 — Yahoo may be **slightly inflating** performance vs better data.
- Yahoo missing bars: 30.0%
- Missing bars are substantial but BOS continuation is a slow signal and should be less sensitive to bar gaps.