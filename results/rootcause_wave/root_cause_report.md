# Root-Cause Attribution Report

Generated: 2026-04-12T14:35:13.288372

## 1. Overall Metrics

| Label                        | Trades |  Sharpe |     PF |   MaxDD |  Win% |            PnL |  Calmar |
|------------------------------|--------|---------|--------|---------|-------|----------------|---------|
| Train                        |    513 |   2.076 |   5.58 |   13.4% | 56.3% |   8,553,133.38 |  365.67 |
| Holdout                      |    253 |   0.154 |   1.11 |   12.7% | 31.2% |       4,215.01 |    0.57 |

## 2. Expectancy Decomposition

| Metric                   |            Train |          Holdout |     Change |
|--------------------------|------------------|------------------|------------|
| win_rate                 |           56.3% |           31.2% |    -25.1% |
| avg_win                  |        36,064.07 |           540.55 | -35,523.52 |
| avg_loss                 |        -9,586.58 |          -239.06 |  +9,347.52 |
| avg_pnl                  |        16,672.77 |            16.66 | -16,656.11 |
| median_win               |        10,168.00 |           152.35 | -10,015.64 |
| median_loss              |        -1,454.20 |          -128.50 |  +1,325.70 |
| p10_pnl                  |        -5,785.54 |          -478.52 |  +5,307.02 |
| p90_pnl                  |        51,947.47 |           362.42 | -51,585.05 |

## 3. Dominant Failure Mechanism

- Win rate dropped by 25.1% (from 56.3% to 31.2%)
- Average winner size change: +98.5%
- Average loser magnitude ratio (holdout/train): 0.02x

**PRIMARY CAUSE: Win-rate collapse** — the strategy generates trades at similar frequency but far fewer are profitable in holdout.
**CONTRIBUTING: Winner size collapse** — winning trades are much smaller.

## 4. Pair-Level Contribution Shift

### Train

| Label                        | Trades |            PnL |   Win% |      Avg PnL | Avg RR |
|------------------------------|--------|----------------|--------|--------------|--------|
| EURUSD                       |      8 |      10,530.47 | 100.0% |     1,316.31 |   0.99 |
| USDJPY                       |    505 |   8,542,602.91 | 55.6% |    16,916.05 |   0.37 |

### Holdout

| Label                        | Trades |            PnL |   Win% |      Avg PnL | Avg RR |
|------------------------------|--------|----------------|--------|--------------|--------|
| EURUSD                       |     41 |      -3,926.11 | 41.5% |       -95.76 |  -0.14 |
| GBPUSD                       |     36 |      -3,620.70 | 30.6% |      -100.57 |  -0.06 |
| USDJPY                       |    176 |      11,761.81 | 29.0% |        66.83 |   0.04 |

### Pair PnL Shift

- EURUSD: Train      10,530.47 -> Holdout      -3,926.11
- GBPUSD: Train           0.00 -> Holdout      -3,620.70
- USDJPY: Train   8,542,602.91 -> Holdout      11,761.81

## 5. Family-Level Contribution Shift

### Train

| Label                        | Trades |            PnL |   Win% |      Avg PnL | Avg RR |
|------------------------------|--------|----------------|--------|--------------|--------|
| bos_continuation             |     55 |    -568,141.61 | 27.3% |   -10,329.85 |   0.39 |
| sweep_reversal               |    458 |   9,121,274.98 | 59.8% |    19,915.45 |   0.38 |

### Holdout

| Label                        | Trades |            PnL |   Win% |      Avg PnL | Avg RR |
|------------------------------|--------|----------------|--------|--------------|--------|
| sweep_reversal               |    210 |      -5,401.01 | 28.6% |       -25.72 |  -0.02 |
| bos_continuation             |     43 |       9,616.02 | 44.2% |       223.63 |   0.09 |

### Family Reversal Analysis

- **bos_continuation**: Train WR 27.3% -> Holdout WR 44.2% | Train PnL -568,142 -> Holdout PnL 9,616
- **sweep_reversal**: Train WR 59.8% -> Holdout WR 28.6% | Train PnL 9,121,275 -> Holdout PnL -5,401

## 6. Direction Decomposition

### Train

| Label                        | Trades |            PnL |   Win% |      Avg PnL | Avg RR |
|------------------------------|--------|----------------|--------|--------------|--------|
| long                         |      8 |      10,530.47 | 100.0% |     1,316.31 |   0.99 |
| short                        |    505 |   8,542,602.91 | 55.6% |    16,916.05 |   0.37 |

### Holdout

| Label                        | Trades |            PnL |   Win% |      Avg PnL | Avg RR |
|------------------------------|--------|----------------|--------|--------------|--------|
| long                         |     77 |      -7,546.80 | 36.4% |       -98.01 |  -0.10 |
| short                        |    176 |      11,761.81 | 29.0% |        66.83 |   0.04 |


## 7. Regime Attribution

### Train

| Label                        | Trades |            PnL |   Win% |      Avg PnL | Avg RR |
|------------------------------|--------|----------------|--------|--------------|--------|
| trending_down                |     66 |    -614,510.31 | 13.6% |    -9,310.76 |   0.30 |
| unknown                      |      2 |      -1,047.75 |  0.0% |      -523.88 |  -0.55 |
| trending_up                  |     38 |     789,215.58 | 65.8% |    20,768.83 |   0.64 |
| high_vol                     |    109 |   1,158,146.94 | 44.0% |    10,625.20 |   0.28 |
| normal                       |    148 |   2,823,481.44 | 68.9% |    19,077.58 |   0.49 |
| low_vol                      |    150 |   4,397,847.47 | 70.0% |    29,318.98 |   0.31 |

### Holdout

| Label                        | Trades |            PnL |   Win% |      Avg PnL | Avg RR |
|------------------------------|--------|----------------|--------|--------------|--------|
| normal                       |    116 |     -10,312.47 | 25.9% |       -88.90 |   0.06 |
| trending_down                |     10 |      -4,068.82 | 10.0% |      -406.88 |  -0.42 |
| high_vol                     |     59 |         198.48 | 33.9% |         3.36 |  -0.17 |
| low_vol                      |     54 |       5,774.71 | 27.8% |       106.94 |  -0.06 |
| trending_up                  |     14 |      12,623.10 | 92.9% |       901.65 |   0.71 |


## 8. Family x Regime Interaction

### Train

| Label                        | Trades |            PnL |   Win% |      Avg PnL | Avg RR |
|------------------------------|--------|----------------|--------|--------------|--------|
| bos_continuation|trending_down |     19 |    -575,286.60 |  0.0% |   -30,278.24 |  -0.05 |
| bos_continuation|high_vol    |     19 |    -114,144.05 | 26.3% |    -6,007.58 |   0.73 |
| bos_continuation|low_vol     |      2 |    -103,343.35 | 50.0% |   -51,671.68 |  -0.37 |
| sweep_reversal|trending_down |     47 |     -39,223.70 | 19.1% |      -834.55 |   0.44 |
| sweep_reversal|unknown       |      2 |      -1,047.75 |  0.0% |      -523.88 |  -0.55 |
| bos_continuation|trending_up |      1 |           0.00 |  0.0% |         0.00 |   0.72 |
| bos_continuation|normal      |     14 |     224,632.40 | 64.3% |    16,045.17 |   0.60 |
| sweep_reversal|trending_up   |     37 |     789,215.58 | 67.6% |    21,330.15 |   0.64 |
| sweep_reversal|high_vol      |     90 |   1,272,291.00 | 47.8% |    14,136.57 |   0.19 |
| sweep_reversal|normal        |    134 |   2,598,849.03 | 69.4% |    19,394.40 |   0.48 |
| sweep_reversal|low_vol       |    148 |   4,501,190.82 | 70.3% |    30,413.45 |   0.32 |

### Holdout

| Label                        | Trades |            PnL |   Win% |      Avg PnL | Avg RR |
|------------------------------|--------|----------------|--------|--------------|--------|
| sweep_reversal|normal        |    103 |      -6,819.76 | 25.2% |       -66.21 |   0.08 |
| sweep_reversal|low_vol       |     43 |      -5,497.97 | 18.6% |      -127.86 |  -0.16 |
| sweep_reversal|trending_down |     10 |      -4,068.82 | 10.0% |      -406.88 |  -0.42 |
| bos_continuation|normal      |     13 |      -3,492.71 | 30.8% |      -268.67 |  -0.08 |
| sweep_reversal|high_vol      |     42 |      -1,430.54 | 33.3% |       -34.06 |  -0.26 |
| bos_continuation|trending_up |      2 |         207.03 | 100.0% |       103.51 |   0.18 |
| bos_continuation|high_vol    |     17 |       1,629.02 | 35.3% |        95.82 |   0.05 |
| bos_continuation|low_vol     |     11 |      11,272.68 | 63.6% |     1,024.79 |   0.34 |
| sweep_reversal|trending_up   |     12 |      12,416.07 | 91.7% |     1,034.67 |   0.80 |


## 9. Month-by-Month

### Train

| Label                        | Trades |            PnL |   Win% |      Avg PnL | Avg RR |
|------------------------------|--------|----------------|--------|--------------|--------|
| 2024-04                      |     93 |     350,158.59 | 81.7% |     3,765.15 |   0.33 |
| 2024-05                      |    155 |     764,773.33 | 54.8% |     4,934.02 |   0.37 |
| 2024-06                      |    144 |   2,974,523.45 | 57.6% |    20,656.41 |   0.33 |
| 2024-07                      |    121 |   4,463,678.00 | 37.2% |    36,889.90 |   0.48 |

### Holdout

| Label                        | Trades |            PnL |   Win% |      Avg PnL | Avg RR |
|------------------------------|--------|----------------|--------|--------------|--------|
| 2025-11                      |     47 |      -1,638.96 | 38.3% |       -34.87 |   0.24 |
| 2025-12                      |    206 |       5,853.96 | 29.6% |        28.42 |  -0.06 |


## 10. Root-Cause Summary

- win-rate collapse (primary)
- winner size collapse
- extreme USDJPY concentration (100% of train PnL)
- sweep_reversal family reversal (profitable in train, loss-making in holdout)