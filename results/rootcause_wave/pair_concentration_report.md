# Pair Concentration and Family Stress Test Report

Generated: 2026-04-12T15:10:37.709944

## 1. Train Period Results

| Variant                          | Pairs                | Trades |  Sharpe |     PF |   MaxDD |  Win% |            PnL |
|----------------------------------|----------------------|--------|---------|--------|---------|-------|----------------|
| sweep_reversal_only | USDJPY only | USDJPY only          |    673 |   2.279 |   3.86 |   12.9% | 57.8% |  14,281,996.90 |
| sweep_reversal_only | All 3 pairs | All 3 pairs          |    691 |   2.272 |   3.61 |   13.6% | 57.3% |  14,200,929.57 |
| sweep_reversal_only | Excl GBPUSD | Excl GBPUSD          |    670 |   2.272 |   3.86 |   12.9% | 58.1% |  14,281,045.36 |
| sweep_reversal_only | Excl EURUSD | Excl EURUSD          |    691 |   2.271 |   3.61 |   13.6% | 57.3% |  14,190,567.14 |
| sweep_plus_bos | Excl GBPUSD     | Excl GBPUSD          |    513 |   2.076 |   5.58 |   13.4% | 56.3% |   8,553,133.38 |
| sweep_plus_bos | All 3 pairs     | All 3 pairs          |    513 |   2.076 |   5.58 |   13.4% | 56.3% |   8,553,133.38 |
| sweep_plus_bos | USDJPY only     | USDJPY only          |    512 |   2.075 |   5.62 |   13.5% | 55.7% |   8,604,535.71 |
| sweep_plus_bos | Excl EURUSD     | Excl EURUSD          |    509 |   2.069 |   5.64 |   13.4% | 56.0% |   8,613,700.78 |
| bos_continuation_only | Excl GBPUSD | Excl GBPUSD          |    432 |   1.948 |   5.90 |   12.8% | 59.7% |   6,175,139.77 |
| bos_continuation_only | All 3 pairs | All 3 pairs          |    432 |   1.948 |   5.90 |   12.8% | 59.7% |   6,175,139.77 |
| bos_continuation_only | USDJPY only | USDJPY only          |    429 |   1.930 |   5.88 |   12.8% | 58.7% |   5,705,609.62 |
| bos_continuation_only | Excl EURUSD | Excl EURUSD          |    426 |   1.924 |   5.90 |   12.8% | 59.2% |   5,710,921.52 |
| sweep_plus_bos | EURUSD only     | EURUSD only          |    125 |   0.115 |   1.17 |   12.7% | 32.0% |       3,683.63 |
| bos_continuation_only | EURUSD only | EURUSD only          |    125 |   0.115 |   1.17 |   12.7% | 32.0% |       3,683.63 |
| sweep_plus_bos | Excl USDJPY     | Excl USDJPY          |     80 |   0.091 |   1.18 |   12.6% | 23.8% |       2,818.57 |
| bos_continuation_only | Excl USDJPY | Excl USDJPY          |     80 |   0.091 |   1.18 |   12.6% | 23.8% |       2,818.57 |
| sweep_plus_bos | GBPUSD only     | GBPUSD only          |     48 |  -0.279 |   0.55 |   12.7% | 29.2% |      -6,456.44 |
| bos_continuation_only | GBPUSD only | GBPUSD only          |     48 |  -0.279 |   0.55 |   12.7% | 29.2% |      -6,456.44 |
| sweep_reversal_only | Excl USDJPY | Excl USDJPY          |     84 |  -0.528 |   0.31 |   12.5% | 21.4% |     -11,912.95 |
| sweep_reversal_only | GBPUSD only | GBPUSD only          |     66 |  -0.832 |   0.01 |   12.6% |  1.5% |     -12,626.39 |
| sweep_reversal_only | EURUSD only | EURUSD only          |     83 |  -0.838 |   0.14 |   12.7% | 14.5% |     -11,827.03 |

## 2. Holdout Period Results

| Variant                          | Pairs                | Trades |  Sharpe |     PF |   MaxDD |  Win% |            PnL |
|----------------------------------|----------------------|--------|---------|--------|---------|-------|----------------|
| sweep_plus_bos | USDJPY only     | USDJPY only          |    330 |   1.172 |   2.04 |   12.5% | 34.8% |      71,845.63 |
| sweep_plus_bos | Excl GBPUSD     | Excl GBPUSD          |    363 |   1.163 |   1.99 |   12.8% | 38.8% |      70,590.01 |
| bos_continuation_only | Excl GBPUSD | Excl GBPUSD          |    251 |   0.862 |   1.93 |   12.6% | 35.5% |      38,606.59 |
| bos_continuation_only | USDJPY only | USDJPY only          |    220 |   0.850 |   1.96 |   12.6% | 29.1% |      38,678.47 |
| sweep_reversal_only | USDJPY only | USDJPY only          |    285 |   0.629 |   1.50 |   12.5% | 32.6% |      25,753.31 |
| sweep_plus_bos | All 3 pairs     | All 3 pairs          |    253 |   0.154 |   1.11 |   12.7% | 31.2% |       4,215.01 |
| bos_continuation_only | All 3 pairs | All 3 pairs          |    253 |   0.154 |   1.11 |   12.7% | 31.2% |       4,215.01 |
| sweep_plus_bos | Excl EURUSD     | Excl EURUSD          |    174 |   0.114 |   1.09 |   12.7% | 27.0% |       2,845.58 |
| bos_continuation_only | Excl EURUSD | Excl EURUSD          |    174 |   0.114 |   1.09 |   12.7% | 27.0% |       2,845.58 |
| sweep_reversal_only | Excl GBPUSD | Excl GBPUSD          |    211 |   0.024 |   1.01 |   12.7% | 28.4% |         276.01 |
| sweep_reversal_only | All 3 pairs | All 3 pairs          |    155 |  -0.379 |   0.70 |   13.0% | 32.3% |      -8,534.93 |
| sweep_reversal_only | Excl EURUSD | Excl EURUSD          |    181 |  -0.456 |   0.66 |   12.6% | 18.8% |      -9,300.70 |
| sweep_plus_bos | EURUSD only     | EURUSD only          |    114 |  -0.818 |   0.49 |   12.8% | 25.4% |      -7,703.89 |
| bos_continuation_only | EURUSD only | EURUSD only          |    114 |  -0.818 |   0.49 |   12.8% | 25.4% |      -7,703.89 |
| sweep_reversal_only | EURUSD only | EURUSD only          |    114 |  -0.818 |   0.49 |   12.8% | 25.4% |      -7,703.89 |
| sweep_reversal_only | Excl USDJPY | Excl USDJPY          |    122 |  -1.094 |   0.29 |   12.9% | 26.2% |     -11,453.74 |
| sweep_plus_bos | Excl USDJPY     | Excl USDJPY          |    126 |  -1.097 |   0.29 |   12.8% | 27.0% |     -12,058.61 |
| bos_continuation_only | Excl USDJPY | Excl USDJPY          |    126 |  -1.097 |   0.29 |   12.8% | 27.0% |     -12,058.61 |
| sweep_reversal_only | GBPUSD only | GBPUSD only          |     83 |  -1.373 |   0.13 |   12.6% |  7.2% |     -11,495.62 |
| sweep_plus_bos | GBPUSD only     | GBPUSD only          |     92 |  -1.380 |   0.15 |   12.5% |  9.8% |     -12,309.40 |
| bos_continuation_only | GBPUSD only | GBPUSD only          |     92 |  -1.380 |   0.15 |   12.5% |  9.8% |     -12,309.40 |

## 3. Is the Edge Just USDJPY?


**sweep_plus_bos**:
- Train: All pairs Sharpe=2.076 vs USDJPY-only Sharpe=2.075
- Holdout: All pairs Sharpe=0.154 vs USDJPY-only Sharpe=1.172

**bos_continuation_only**:
- Train: All pairs Sharpe=1.948 vs USDJPY-only Sharpe=1.930
- Holdout: All pairs Sharpe=0.154 vs USDJPY-only Sharpe=0.850

**sweep_reversal_only**:
- Train: All pairs Sharpe=2.272 vs USDJPY-only Sharpe=2.279
- Holdout: All pairs Sharpe=-0.379 vs USDJPY-only Sharpe=0.629

## 4. Does Multi-Pair Improve OOS Stability?


**sweep_plus_bos**:
- All pairs holdout: Sharpe=0.154, Trades=253
- USDJPY-only holdout: Sharpe=1.172, Trades=330
- Excl USDJPY holdout: Sharpe=-1.097, Trades=126

**bos_continuation_only**:
- All pairs holdout: Sharpe=0.154, Trades=253
- USDJPY-only holdout: Sharpe=0.850, Trades=220
- Excl USDJPY holdout: Sharpe=-1.097, Trades=126

**sweep_reversal_only**:
- All pairs holdout: Sharpe=-0.379, Trades=155
- USDJPY-only holdout: Sharpe=0.629, Trades=285
- Excl USDJPY holdout: Sharpe=-1.094, Trades=122

## 5. Family Comparison (All Pairs)


### Train

- **sweep_plus_bos**: Sharpe=2.076 | PF=5.58 | DD=13.4% | Trades=513 | Win%=56.3%
- **bos_continuation_only**: Sharpe=1.948 | PF=5.90 | DD=12.8% | Trades=432 | Win%=59.7%
- **sweep_reversal_only**: Sharpe=2.272 | PF=3.61 | DD=13.6% | Trades=691 | Win%=57.3%

### Holdout

- **sweep_plus_bos**: Sharpe=0.154 | PF=1.11 | DD=12.7% | Trades=253 | Win%=31.2%
- **bos_continuation_only**: Sharpe=0.154 | PF=1.11 | DD=12.7% | Trades=253 | Win%=31.2%
- **sweep_reversal_only**: Sharpe=-0.379 | PF=0.70 | DD=13.0% | Trades=155 | Win%=32.3%