# Holdout Regime Diagnostics Report

Generated: 2026-04-12T13:24:23.357416

## Data Split
- Train: 2024-04-10 to 2025-06-23 (22,185 bars total)
- Holdout: 2025-11-17 to 2026-04-10 (7,367 bars total)

## Overall Metrics Comparison

| Period                    | Trades |  Sharpe |     PF |   MaxDD |  Win% |          PnL |  Calmar |
|---------------------------|--------|---------|--------|---------|-------|--------------|---------|
| Train                     |    513 |   2.076 |   5.58 |   13.4% | 56.3% | 8,553,133.38 |  365.67 |
| Holdout                   |    253 |   0.154 |   1.11 |   12.7% | 31.2% |     4,215.01 |    0.57 |


### Degradation Summary
- Sharpe: 2.076 -> 0.154 (-92.6%)
- Profit Factor: 5.58 -> 1.11
- Win Rate: 56.3% -> 31.2%
- Avg PnL: 16,672.77 -> 16.66
- Max DD: 13.4% -> 12.7%
- Trade Count: 513 -> 253

## Regime Distribution: Train vs Holdout

### Train Period

**Volatility**:
  - normal: 34.3%
  - low_vol: 28.6%
  - high_vol: 16.8%
  - trending_down: 10.6%
  - trending_up: 9.7%
**Trend**:
  - ranging: 79.1%
  - trending_up: 11.5%
  - trending_down: 9.4%
**Spread**:
  - normal: 39.2%
  - tight_spread: 31.0%
  - wide_spread: 29.8%


### Holdout Period

**Volatility**:
  - normal: 36.0%
  - low_vol: 28.5%
  - high_vol: 20.8%
  - trending_up: 8.3%
  - trending_down: 6.5%
**Trend**:
  - ranging: 82.2%
  - trending_up: 10.9%
  - trending_down: 6.9%
**Spread**:
  - normal: 36.7%
  - tight_spread: 32.1%
  - wide_spread: 31.1%


### Regime Shift Analysis

- **volatility/high_vol**: 16.8% -> 20.8% (+4.0%)
- **volatility/trending_down**: 10.6% -> 6.5% (-4.1%)
- **trend/ranging**: 79.1% -> 82.2% (+3.0%)

## Month-by-Month Decomposition

### Train

| Label                     | Trades |          PnL |   Win% |    Avg PnL | Avg RR |
|---------------------------|--------|--------------|--------|------------|--------|
| 2024-04                   |     93 |   350,158.59 | 81.7% |   3,765.15 |   0.33 |
| 2024-05                   |    155 |   764,773.33 | 54.8% |   4,934.02 |   0.37 |
| 2024-06                   |    144 | 2,974,523.45 | 57.6% |  20,656.41 |   0.33 |
| 2024-07                   |    121 | 4,463,678.00 | 37.2% |  36,889.90 |   0.48 |


### Holdout

| Label                     | Trades |          PnL |   Win% |    Avg PnL | Avg RR |
|---------------------------|--------|--------------|--------|------------|--------|
| 2025-11                   |     47 |    -1,638.96 | 38.3% |     -34.87 |   0.24 |
| 2025-12                   |    206 |     5,853.96 | 29.6% |      28.42 |  -0.06 |


## Pair-Level Attribution

### Train

| Label                     | Trades |          PnL |   Win% |    Avg PnL | Avg RR |
|---------------------------|--------|--------------|--------|------------|--------|
| EURUSD                    |      8 |    10,530.47 | 100.0% |   1,316.31 |   0.99 |
| USDJPY                    |    505 | 8,542,602.91 | 55.6% |  16,916.05 |   0.37 |


### Holdout

| Label                     | Trades |          PnL |   Win% |    Avg PnL | Avg RR |
|---------------------------|--------|--------------|--------|------------|--------|
| EURUSD                    |     41 |    -3,926.11 | 41.5% |     -95.76 |  -0.14 |
| GBPUSD                    |     36 |    -3,620.70 | 30.6% |    -100.57 |  -0.06 |
| USDJPY                    |    176 |    11,761.81 | 29.0% |      66.83 |   0.04 |


## Family-Level Attribution

### Train

| Label                     | Trades |          PnL |   Win% |    Avg PnL | Avg RR |
|---------------------------|--------|--------------|--------|------------|--------|
| bos_continuation          |     55 |  -568,141.61 | 27.3% | -10,329.85 |   0.39 |
| sweep_reversal            |    458 | 9,121,274.98 | 59.8% |  19,915.45 |   0.38 |


### Holdout

| Label                     | Trades |          PnL |   Win% |    Avg PnL | Avg RR |
|---------------------------|--------|--------------|--------|------------|--------|
| sweep_reversal            |    210 |    -5,401.01 | 28.6% |     -25.72 |  -0.02 |
| bos_continuation          |     43 |     9,616.02 | 44.2% |     223.63 |   0.09 |


## Session Attribution

### Train

| Label                     | Trades |          PnL |   Win% |    Avg PnL | Avg RR |
|---------------------------|--------|--------------|--------|------------|--------|
| unknown                   |    513 | 8,553,133.38 | 56.3% |  16,672.77 |   0.38 |


### Holdout

| Label                     | Trades |          PnL |   Win% |    Avg PnL | Avg RR |
|---------------------------|--------|--------------|--------|------------|--------|
| unknown                   |    253 |     4,215.01 | 31.2% |      16.66 |  -0.00 |


## Direction Attribution (Long vs Short)

### Train

| Label                     | Trades |          PnL |   Win% |    Avg PnL | Avg RR |
|---------------------------|--------|--------------|--------|------------|--------|
| long                      |      8 |    10,530.47 | 100.0% |   1,316.31 |   0.99 |
| short                     |    505 | 8,542,602.91 | 55.6% |  16,916.05 |   0.37 |


### Holdout

| Label                     | Trades |          PnL |   Win% |    Avg PnL | Avg RR |
|---------------------------|--------|--------------|--------|------------|--------|
| long                      |     77 |    -7,546.80 | 36.4% |     -98.01 |  -0.10 |
| short                     |    176 |    11,761.81 | 29.0% |      66.83 |   0.04 |


## Regime Attribution

### Train

| Label                     | Trades |          PnL |   Win% |    Avg PnL | Avg RR |
|---------------------------|--------|--------------|--------|------------|--------|
| trending_down             |     66 |  -614,510.31 | 13.6% |  -9,310.76 |   0.30 |
| unknown                   |      2 |    -1,047.75 |  0.0% |    -523.88 |  -0.55 |
| trending_up               |     38 |   789,215.58 | 65.8% |  20,768.83 |   0.64 |
| high_vol                  |    109 | 1,158,146.94 | 44.0% |  10,625.20 |   0.28 |
| normal                    |    148 | 2,823,481.44 | 68.9% |  19,077.58 |   0.49 |
| low_vol                   |    150 | 4,397,847.47 | 70.0% |  29,318.98 |   0.31 |


### Holdout

| Label                     | Trades |          PnL |   Win% |    Avg PnL | Avg RR |
|---------------------------|--------|--------------|--------|------------|--------|
| normal                    |    116 |   -10,312.47 | 25.9% |     -88.90 |   0.06 |
| trending_down             |     10 |    -4,068.82 | 10.0% |    -406.88 |  -0.42 |
| high_vol                  |     59 |       198.48 | 33.9% |       3.36 |  -0.17 |
| low_vol                   |     54 |     5,774.71 | 27.8% |     106.94 |  -0.06 |
| trending_up               |     14 |    12,623.10 | 92.9% |     901.65 |   0.71 |


## Pair x Regime Interaction

### Train

| Label                     | Trades |          PnL |   Win% |    Avg PnL | Avg RR |
|---------------------------|--------|--------------|--------|------------|--------|
| USDJPY|trending_down      |     66 |  -614,510.31 | 13.6% |  -9,310.76 |   0.30 |
| USDJPY|unknown            |      2 |    -1,047.75 |  0.0% |    -523.88 |  -0.55 |
| EURUSD|high_vol           |      3 |     4,498.93 | 100.0% |   1,499.64 |   0.99 |
| EURUSD|normal             |      5 |     6,031.54 | 100.0% |   1,206.31 |   0.98 |
| USDJPY|trending_up        |     38 |   789,215.58 | 65.8% |  20,768.83 |   0.64 |
| USDJPY|high_vol           |    106 | 1,153,648.01 | 42.5% |  10,883.47 |   0.26 |
| USDJPY|normal             |    143 | 2,817,449.90 | 67.8% |  19,702.45 |   0.48 |
| USDJPY|low_vol            |    150 | 4,397,847.47 | 70.0% |  29,318.98 |   0.31 |


### Holdout

| Label                     | Trades |          PnL |   Win% |    Avg PnL | Avg RR |
|---------------------------|--------|--------------|--------|------------|--------|
| USDJPY|normal             |     91 |    -6,312.78 | 25.3% |     -69.37 |   0.07 |
| USDJPY|trending_down      |      9 |    -3,622.27 | 11.1% |    -402.47 |  -0.36 |
| EURUSD|low_vol            |      7 |    -3,471.99 | 14.3% |    -496.00 |  -0.37 |
| GBPUSD|normal             |     15 |    -3,155.39 |  6.7% |    -210.36 |  -0.21 |
| EURUSD|normal             |     10 |      -844.30 | 60.0% |     -84.43 |   0.42 |
| GBPUSD|low_vol            |      9 |      -806.56 | 33.3% |     -89.62 |   0.02 |
| USDJPY|high_vol           |     27 |      -470.83 | 22.2% |     -17.44 |  -0.13 |
| GBPUSD|trending_down      |      1 |      -446.54 |  0.0% |    -446.54 |  -1.02 |
| GBPUSD|high_vol           |      8 |       279.13 | 50.0% |      34.89 |   0.10 |
| EURUSD|high_vol           |     24 |       390.18 | 41.7% |      16.26 |  -0.31 |
| GBPUSD|trending_up        |      3 |       508.67 | 100.0% |     169.56 |   0.39 |
| USDJPY|low_vol            |     38 |    10,053.26 | 28.9% |     264.56 |  -0.02 |
| USDJPY|trending_up        |     11 |    12,114.43 | 90.9% |   1,101.31 |   0.80 |


## Family x Regime Interaction

### Train

| Label                     | Trades |          PnL |   Win% |    Avg PnL | Avg RR |
|---------------------------|--------|--------------|--------|------------|--------|
| bos_continuation|trending_down |     19 |  -575,286.60 |  0.0% | -30,278.24 |  -0.05 |
| bos_continuation|high_vol |     19 |  -114,144.05 | 26.3% |  -6,007.58 |   0.73 |
| bos_continuation|low_vol  |      2 |  -103,343.35 | 50.0% | -51,671.68 |  -0.37 |
| sweep_reversal|trending_down |     47 |   -39,223.70 | 19.1% |    -834.55 |   0.44 |
| sweep_reversal|unknown    |      2 |    -1,047.75 |  0.0% |    -523.88 |  -0.55 |
| bos_continuation|trending_up |      1 |         0.00 |  0.0% |       0.00 |   0.72 |
| bos_continuation|normal   |     14 |   224,632.40 | 64.3% |  16,045.17 |   0.60 |
| sweep_reversal|trending_up |     37 |   789,215.58 | 67.6% |  21,330.15 |   0.64 |
| sweep_reversal|high_vol   |     90 | 1,272,291.00 | 47.8% |  14,136.57 |   0.19 |
| sweep_reversal|normal     |    134 | 2,598,849.03 | 69.4% |  19,394.40 |   0.48 |
| sweep_reversal|low_vol    |    148 | 4,501,190.82 | 70.3% |  30,413.45 |   0.32 |


### Holdout

| Label                     | Trades |          PnL |   Win% |    Avg PnL | Avg RR |
|---------------------------|--------|--------------|--------|------------|--------|
| sweep_reversal|normal     |    103 |    -6,819.76 | 25.2% |     -66.21 |   0.08 |
| sweep_reversal|low_vol    |     43 |    -5,497.97 | 18.6% |    -127.86 |  -0.16 |
| sweep_reversal|trending_down |     10 |    -4,068.82 | 10.0% |    -406.88 |  -0.42 |
| bos_continuation|normal   |     13 |    -3,492.71 | 30.8% |    -268.67 |  -0.08 |
| sweep_reversal|high_vol   |     42 |    -1,430.54 | 33.3% |     -34.06 |  -0.26 |
| bos_continuation|trending_up |      2 |       207.03 | 100.0% |     103.51 |   0.18 |
| bos_continuation|high_vol |     17 |     1,629.02 | 35.3% |      95.82 |   0.05 |
| bos_continuation|low_vol  |     11 |    11,272.68 | 63.6% |   1,024.79 |   0.34 |
| sweep_reversal|trending_up |     12 |    12,416.07 | 91.7% |   1,034.67 |   0.80 |


## Signal Funnel Comparison

### Train

# Detector Diagnostics Report

## Signal Funnel by Family

| Family | Scans | Raw Signals | After Filters | Orders | Trades | Conversion |
|--------|-------|-------------|---------------|--------|--------|------------|
| bos_continuation | 22,095 | 21,182 | 21,182 | 0 | 0 | 0.00% |
| sweep_reversal | 22,095 | 38,016 | 38,016 | 0 | 0 | 0.00% |

## Rejection Breakdown

| Family | No Htf Bias | No Swept Levels | No Entry Zone | No Bos Breaks | Regime Filtered | Score Too Low | Rr Too Low | Risk Distance Zero |
|--------|---|---|---|---|---|---|---|---|
| bos_continuation | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| sweep_reversal | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## Signals by Pair

| Family | EURUSD | GBPUSD | USDJPY | Total |
|--------|---|---|---|-------|
| bos_continuation | 7286 | 7187 | 6709 | 21182 |
| sweep_reversal | 17907 | 12565 | 7544 | 38016 |

## Signals by Session


## Inactive / Weak Family Alerts

- **bos_continuation**: 21182 signals generated but 0 trades filled (filtered: score=0, rr=0)
- **sweep_reversal**: 38016 signals generated but 0 trades filled (filtered: score=0, rr=0)

### Holdout

# Detector Diagnostics Report

## Signal Funnel by Family

| Family | Scans | Raw Signals | After Filters | Orders | Trades | Conversion |
|--------|-------|-------------|---------------|--------|--------|------------|
| bos_continuation | 7,277 | 6,802 | 6,802 | 0 | 0 | 0.00% |
| sweep_reversal | 7,277 | 13,048 | 13,048 | 0 | 0 | 0.00% |

## Rejection Breakdown

| Family | No Htf Bias | No Swept Levels | No Entry Zone | No Bos Breaks | Regime Filtered | Score Too Low | Rr Too Low | Risk Distance Zero |
|--------|---|---|---|---|---|---|---|---|
| bos_continuation | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| sweep_reversal | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## Signals by Pair

| Family | EURUSD | GBPUSD | USDJPY | Total |
|--------|---|---|---|-------|
| bos_continuation | 2301 | 2207 | 2294 | 6802 |
| sweep_reversal | 6194 | 3449 | 3405 | 13048 |

## Signals by Session


## Inactive / Weak Family Alerts

- **bos_continuation**: 6802 signals generated but 0 trades filled (filtered: score=0, rr=0)
- **sweep_reversal**: 13048 signals generated but 0 trades filled (filtered: score=0, rr=0)